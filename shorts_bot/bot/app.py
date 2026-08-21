import asyncio
import re
import uuid
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message

from shorts_bot.bot.keyboards import duration_keyboard
from shorts_bot.bot.states import JobSettings
from shorts_bot.config import get_settings
from shorts_bot.db.repository import create_job
from shorts_bot.db.session import initialize_database
from shorts_bot.worker.tasks import process_video

router = Router()
URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer("Отправьте ссылку на видео или видеофайл до 2 ГБ.")


@router.message(F.text.regexp(URL_PATTERN))
async def receive_url(message: Message, state: FSMContext) -> None:
    url = URL_PATTERN.search(message.text or "").group(0)
    await state.set_data({"source_type": "url", "source": url})
    await state.set_state(JobSettings.choosing_duration)
    await message.answer("Выберите длительность ролика.", reply_markup=duration_keyboard())


@router.message(F.video | F.document)
async def receive_file(message: Message, state: FSMContext, bot: Bot) -> None:
    document = message.video or message.document
    if document is None:
        return
    settings = get_settings()
    if document.file_size and document.file_size > settings.max_upload_bytes:
        await message.answer("Файл больше допустимых 2 ГБ.")
        return

    suffix = Path(document.file_name or "video.mp4").suffix or ".mp4"
    job_id = str(uuid.uuid4())
    target = settings.media_root / "uploads" / f"{job_id}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    await bot.download(document, destination=target)
    await state.set_data({"source_type": "file", "source": str(target)})
    await state.set_state(JobSettings.choosing_duration)
    await message.answer("Файл принят. Выберите длительность ролика.", reply_markup=duration_keyboard())


@router.callback_query(JobSettings.choosing_duration, F.data.startswith("duration:"))
async def enqueue_job(callback: CallbackQuery, state: FSMContext) -> None:
    _, minimum, maximum = callback.data.split(":")
    data = await state.get_data()
    job_id = str(uuid.uuid4())
    await create_job(
        job_id, callback.message.chat.id, data["source_type"], data["source"], int(minimum), int(maximum)
    )
    process_video.apply_async(
        kwargs={
            "source_type": data["source_type"],
            "source": data["source"],
            "min_duration": int(minimum),
            "max_duration": int(maximum),
            "chat_id": callback.message.chat.id,
        },
        task_id=job_id,
    )
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        f"Задача принята. ID: <code>{job_id}</code>\n"
        "Обработка идёт в фоне. Готовые ролики будут отправлены сюда."
    )


async def main() -> None:
    settings = get_settings()
    bot = Bot(settings.telegram_bot_token)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(router)
    await initialize_database()
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
