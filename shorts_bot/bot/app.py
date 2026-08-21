import asyncio
import re
import shutil
import uuid
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from shorts_bot.bot.access import AccessMiddleware
from openai import OpenAI

from shorts_bot.bot.keyboards import admin_keyboard, duration_keyboard, format_keyboard, start_keyboard
from shorts_bot.bot.states import AdminStates, AiStates, JobSettings
from shorts_bot.config import get_settings
from shorts_bot.db.repository import add_user, count_active_jobs, create_job, get_active_job_ids, get_active_media_sources, get_banner, get_job, get_user_details, list_users, remove_user, save_banner, set_banner_enabled
from shorts_bot.db.session import initialize_database
from shorts_bot.worker.tasks import process_video

router = Router()
URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
STATUS_TEXT = {"QUEUED": "⏳ В очереди на обработку...", "DOWNLOADING": "📥 Скачиваю видео...", "TRANSCRIBING": "🎧 Распознаю речь...", "ANALYZING": "🧠 Ищу самые цепляющие моменты...", "RENDERING": "✂️ Нарезаю и монтирую ролики...", "DELIVERING": "🚀 Отправляю готовые ролики!", "DONE": "✅ Готово!", "FAILED": "⚠️ Не удалось обработать видео. Попробуйте другую ссылку или файл."}
MAX_QUEUE_SIZE = 30


def is_admin(user_id: int) -> bool:
    return user_id == get_settings().admin_id


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(
        "👋 Добро пожаловать в qOneShorts Creator!\n\n"
        "Отправьте ссылку или видео, а я найду лучшие моменты и превращу их в готовые Shorts.\n\n"
        "Можно отправлять новые ссылки, пока предыдущие ролики обрабатываются: они встанут в очередь.\n"
        "Лимит очереди — 30 ссылок.",
        reply_markup=start_keyboard(),
    )


@router.callback_query(F.data == "settings:open")
async def settings_stub(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer("⚙️ Настройки пока пусты. Здесь появятся параметры обработки видео.", reply_markup=start_keyboard())


@router.callback_query(F.data == "ai:open")
async def open_ai(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AiStates.chatting)
    await callback.answer()
    await callback.message.answer("🧠 Режим ИИ включён. Напишите вопрос. Чтобы выйти, отправьте /close")


@router.message(Command("close"))
async def close_ai(message: Message, state: FSMContext) -> None:
    if await state.get_state() == AiStates.chatting.state:
        await state.clear()
        await message.answer("✅ Режим ИИ закрыт.", reply_markup=start_keyboard())


@router.message(AiStates.chatting, F.text)
async def ask_ai(message: Message) -> None:
    settings = get_settings()
    if not settings.llm_api_key:
        await message.answer("ИИ сейчас недоступен: не задан LLM_API_KEY.")
        return
    try:
        answer = await asyncio.to_thread(_ask_ai_sync, message.text or "", settings)
        await message.answer(answer)
    except Exception:
        await message.answer("Не удалось получить ответ от ИИ. Попробуйте ещё раз.")


def _ask_ai_sync(prompt: str, settings) -> str:
    client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
    if settings.llm_api_style == "responses":
        response = client.responses.create(
            model=settings.llm_model,
            instructions="Отвечай кратко и по-русски. Ты помощник сервиса создания Shorts.",
            input=prompt,
        )
        return response.output_text or "Не смог сформировать ответ."
    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": "Отвечай кратко и по-русски. Ты помощник сервиса создания Shorts."},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content or "Не смог сформировать ответ."


async def accept_source(message: Message, state: FSMContext, source_type: str, source: str) -> None:
    await accept_sources(message, state, [(source_type, source)])


async def accept_sources(message: Message, state: FSMContext, sources: list[tuple[str, str]]) -> None:
    current = await state.get_data()
    pending = list(current.get("sources", []))
    active = await count_active_jobs(message.chat.id)
    if active + len(pending) + len(sources) > MAX_QUEUE_SIZE:
        available = max(0, MAX_QUEUE_SIZE - active - len(pending))
        await message.answer(
            f"⚠️ В очереди максимум {MAX_QUEUE_SIZE} ссылок. Сейчас можно добавить: {available}."
        )
        return
    pending.extend({"source_type": source_type, "source": source} for source_type, source in sources)
    await state.update_data(sources=pending)
    current_state = await state.get_state()
    if current_state not in {JobSettings.choosing_format.state, JobSettings.choosing_duration.state}:
        await state.set_state(JobSettings.choosing_format)
        await message.answer(
            f"Добавлено источников: {len(pending)}. Выберите формат готового видео.",
            reply_markup=format_keyboard(),
        )
    elif current_state == JobSettings.choosing_format.state:
        await message.answer(f"✅ Ссылка добавлена в текущую подборку. Всего источников: {len(pending)}")
    else:
        await message.answer(f"✅ Ссылка добавлена в текущую подборку. Всего источников: {len(pending)}")


@router.message(F.text.regexp(URL_PATTERN))
async def receive_url(message: Message, state: FSMContext) -> None:
    urls = URL_PATTERN.findall(message.text or "")
    if urls:
        await accept_sources(message, state, [("url", url.rstrip(".,)]")) for url in urls])


@router.message(AdminStates.waiting_banner, F.video | F.document)
async def upload_banner(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    media = message.video or message.document
    if not media:
        await message.answer("Пришлите видеофайл баннера.")
        return
    path = get_settings().media_root / "banner.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    await bot.download(media, destination=path)
    await save_banner(str(path), message.from_user.id)
    await state.clear()
    await message.answer("✅ Баннер сохранён и включён.", reply_markup=admin_keyboard())


@router.message(F.video | F.document)
async def receive_file(message: Message, state: FSMContext, bot: Bot) -> None:
    document = message.video or message.document
    if not document:
        return
    if document.file_size and document.file_size > get_settings().max_upload_bytes:
        await message.answer("Файл больше допустимых 2 ГБ.")
        return
    path = get_settings().media_root / "uploads" / f"{uuid.uuid4()}{Path(document.file_name or 'video.mp4').suffix or '.mp4'}"
    path.parent.mkdir(parents=True, exist_ok=True)
    await bot.download(document, destination=path)
    await accept_source(message, state, "file", str(path))


@router.callback_query(JobSettings.choosing_format, F.data.startswith("format:"))
async def choose_format(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(video_format=callback.data.removeprefix("format:"))
    await state.set_state(JobSettings.choosing_duration)
    await callback.answer()
    await callback.message.edit_text("Выберите длительность ролика.", reply_markup=duration_keyboard())


@router.callback_query(JobSettings.choosing_duration, F.data.startswith("duration:"))
async def enqueue_job(callback: CallbackQuery, state: FSMContext) -> None:
    _, minimum, maximum = callback.data.split(":")
    data = await state.get_data()
    sources = data.get("sources", [])
    if not sources:
        await callback.answer("Источник не найден", show_alert=True)
        return
    active = await count_active_jobs(callback.message.chat.id)
    if active + len(sources) > MAX_QUEUE_SIZE:
        await callback.answer(f"Очередь заполнена: максимум {MAX_QUEUE_SIZE} ссылок", show_alert=True)
        return
    video_format = data.get("video_format", "9:16")
    await state.clear()
    await callback.answer()
    for index, item in enumerate(sources):
        job_id = str(uuid.uuid4())
        status_message = callback.message if index == 0 else await callback.message.answer("⏳ В очереди на обработку...")
        await create_job(job_id, callback.message.chat.id, item["source_type"], item["source"], int(minimum), int(maximum), video_format, status_message.message_id)
        process_video.apply_async(kwargs={"source_type": item["source_type"], "source": item["source"], "min_duration": int(minimum), "max_duration": int(maximum), "chat_id": callback.message.chat.id, "video_format": video_format}, task_id=job_id)
        if index == 0:
            await status_message.edit_text(STATUS_TEXT["QUEUED"] if "QUEUED" in STATUS_TEXT else "⏳ В очереди на обработку...")
        asyncio.create_task(poll_status(callback.message.bot, callback.message.chat.id, status_message.message_id, job_id))


async def poll_status(bot: Bot, chat_id: int, message_id: int, job_id: str) -> None:
    previous = None
    for _ in range(1800):
        await asyncio.sleep(2)
        job = await get_job(job_id)
        if not job:
            return
        text = STATUS_TEXT.get(job.status, "⏳ Обрабатываю видео...")
        if job.status == "RENDERING" and job.progress_total:
            text = f"✂️ Нарезаю и монтирую ролики ({job.progress_current or 0} из {job.progress_total})..."
        if text != previous:
            try:
                await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
                previous = text
            except Exception:
                pass
        if job.status in {"DONE", "FAILED"}:
            return


@router.message(Command("admin"))
async def admin(message: Message) -> None:
    if is_admin(message.from_user.id):
        await message.answer("⚙️ Админка", reply_markup=admin_keyboard())


@router.callback_query(F.data == "admin:users")
async def users_menu(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id): return
    users = await list_users()
    rows = [[InlineKeyboardButton(text="➕ Добавить пользователя", callback_data="admin:add_user")]]
    rows += [[InlineKeyboardButton(text=f"👤 @{u.username or 'без_username'} ({u.telegram_id})", callback_data=f"admin:user:{u.telegram_id}")] for u in users]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:back")])
    await callback.message.edit_text("👥 Пользователи", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data == "admin:add_user")
async def add_user_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if is_admin(callback.from_user.id):
        await state.set_state(AdminStates.waiting_user)
        await callback.message.edit_text("Пришлите Telegram ID пользователя или перешлите его сообщение.")
    await callback.answer()


@router.message(AdminStates.waiting_user)
async def add_user_handler(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id): return
    forwarded = message.forward_from
    raw_id = forwarded.id if forwarded else int(message.text) if (message.text or "").strip().isdigit() else None
    if not raw_id:
        await message.answer("Нужен числовой Telegram ID или пересланное сообщение.")
        return
    await add_user(raw_id, forwarded.username if forwarded else None, message.from_user.id)
    await state.clear()
    await message.answer(f"✅ Доступ добавлен: {raw_id}", reply_markup=admin_keyboard())


@router.callback_query(F.data.startswith("admin:user:"))
async def user_card(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id): return
    user_id = int(callback.data.rsplit(":", 1)[1])
    user, jobs_count = await get_user_details(user_id)
    username = f"@{user.username}" if user and user.username else "не указан"
    added = user.added_at.strftime("%Y-%m-%d %H:%M") if user and user.added_at else "неизвестно"
    rows = [[InlineKeyboardButton(text="🗑 Удалить доступ", callback_data=f"admin:remove:{user_id}")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:users")]]
    await callback.message.edit_text(f"👤 Пользователь\n\nID: {user_id}\nUsername: {username}\nДобавлен: {added}\nРоликов обработано: {jobs_count}", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:remove:"))
async def remove_user_handler(callback: CallbackQuery) -> None:
    if is_admin(callback.from_user.id):
        await remove_user(int(callback.data.rsplit(":", 1)[1]))
        await callback.answer("Доступ удалён")
        await users_menu(callback)


@router.callback_query(F.data == "admin:banner")
async def banner_menu(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id): return
    banner = await get_banner()
    enabled = banner and banner.enabled
    rows = [[InlineKeyboardButton(text="🔁 Загрузить/заменить баннер", callback_data="admin:upload_banner")]]
    if banner and banner.file_path:
        rows.append([InlineKeyboardButton(text=f"{'✅' if enabled else '⬜️'} Переключить баннер", callback_data="admin:toggle_banner")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:back")])
    await callback.message.edit_text("🖼 Баннер\n\nПришлите короткое видео для наложения сверху.", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data == "admin:upload_banner")
async def upload_banner_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if is_admin(callback.from_user.id):
        await state.set_state(AdminStates.waiting_banner)
        await callback.message.edit_text("Пришлите видео баннера.")
    await callback.answer()


@router.callback_query(F.data == "admin:toggle_banner")
async def toggle_banner(callback: CallbackQuery) -> None:
    if is_admin(callback.from_user.id):
        banner = await get_banner()
        await set_banner_enabled(not (banner and banner.enabled))
        await callback.answer("Состояние изменено")
        await banner_menu(callback)


@router.callback_query(F.data == "admin:back")
async def admin_back(callback: CallbackQuery) -> None:
    if is_admin(callback.from_user.id):
        await callback.message.edit_text("⚙️ Админка", reply_markup=admin_keyboard())
    await callback.answer()


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} Б"


@router.callback_query(F.data == "admin:memory")
async def memory_menu(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    root = get_settings().media_root
    jobs_size = _directory_size(root / "jobs")
    uploads_size = _directory_size(root / "uploads")
    banner_path = root / "banner.mp4"
    banner_size = banner_path.stat().st_size if banner_path.is_file() else 0
    total = _directory_size(root)
    rows = [
        [InlineKeyboardButton(text="🗑 Удалить обработанные и скачанные видео", callback_data="admin:memory:clear")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:back")],
    ]
    await callback.message.edit_text(
        "💾 Память\n\n"
        f"Всего в media: {_format_bytes(total)}\n"
        f"Обработанные видео (jobs): {_format_bytes(jobs_size)}\n"
        f"Загруженные видео (uploads): {_format_bytes(uploads_size)}\n"
        f"Баннер: {_format_bytes(banner_size)}\n\n"
        "Кнопка удаления очищает только jobs и uploads. Баннер сохраняется.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:memory:clear")
async def clear_memory(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    root = get_settings().media_root
    removed = 0
    active_job_ids = await get_active_job_ids()
    jobs_path = root / "jobs"
    if jobs_path.exists():
        for path in jobs_path.iterdir():
            if path.name in active_job_ids:
                continue
            removed += _directory_size(path)
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

    active_sources = {Path(source).resolve() for source in await get_active_media_sources()}
    uploads_path = root / "uploads"
    if uploads_path.exists():
        for path in uploads_path.iterdir():
            if path.resolve() in active_sources:
                continue
            removed += _directory_size(path)
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    await callback.answer(f"Удалено: {_format_bytes(removed)}")
    await memory_menu(callback)


async def main() -> None:
    settings = get_settings()
    bot = Bot(settings.telegram_bot_token)
    dispatcher = Dispatcher(storage=MemoryStorage())
    router.message.outer_middleware(AccessMiddleware())
    router.callback_query.outer_middleware(AccessMiddleware())
    dispatcher.include_router(router)
    await initialize_database()
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
