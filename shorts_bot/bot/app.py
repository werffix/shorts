import asyncio
import re
import uuid
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from shorts_bot.bot.access import AccessMiddleware
from shorts_bot.bot.keyboards import admin_keyboard, duration_keyboard, format_keyboard
from shorts_bot.bot.states import AdminStates, JobSettings
from shorts_bot.config import get_settings
from shorts_bot.db.repository import add_user, create_job, get_banner, get_job, get_user_details, list_users, remove_user, save_banner, set_banner_enabled
from shorts_bot.db.session import initialize_database
from shorts_bot.worker.tasks import process_video

router = Router()
URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
STATUS_TEXT = {"DOWNLOADING": "📥 Скачиваю видео...", "TRANSCRIBING": "🎧 Распознаю речь...", "ANALYZING": "🧠 Ищу самые цепляющие моменты...", "RENDERING": "✂️ Нарезаю и монтирую ролики...", "DELIVERING": "🚀 Отправляю готовые ролики!", "DONE": "✅ Готово!", "FAILED": "⚠️ Не удалось обработать видео. Попробуйте другую ссылку или файл."}


def is_admin(user_id: int) -> bool:
    return user_id == get_settings().admin_id


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer("Отправьте ссылку на видео или видеофайл до 2 ГБ.")


async def accept_source(message: Message, state: FSMContext, source_type: str, source: str) -> None:
    await state.set_data({"source_type": source_type, "source": source})
    await state.set_state(JobSettings.choosing_format)
    await message.answer("Выберите формат готового видео.", reply_markup=format_keyboard())


@router.message(F.text.regexp(URL_PATTERN))
async def receive_url(message: Message, state: FSMContext) -> None:
    await accept_source(message, state, "url", URL_PATTERN.search(message.text or "").group(0))


@router.message(AdminStates.waiting_banner, F.video)
async def upload_banner(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    path = get_settings().media_root / "banner.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    await bot.download(message.video, destination=path)
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
    job_id = str(uuid.uuid4())
    video_format = data.get("video_format", "9:16")
    await create_job(job_id, callback.message.chat.id, data["source_type"], data["source"], int(minimum), int(maximum), video_format, callback.message.message_id)
    process_video.apply_async(kwargs={"source_type": data["source_type"], "source": data["source"], "min_duration": int(minimum), "max_duration": int(maximum), "chat_id": callback.message.chat.id, "video_format": video_format}, task_id=job_id)
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(STATUS_TEXT["DOWNLOADING"])
    asyncio.create_task(poll_status(callback.message.bot, callback.message.chat.id, callback.message.message_id, job_id))


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
