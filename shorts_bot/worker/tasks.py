import asyncio
from pathlib import Path

from aiogram import Bot

from shorts_bot.config import get_settings
from shorts_bot.db.repository import get_banner, update_job
from shorts_bot.db.session import initialize_database
from shorts_bot.pipeline.downloader import download_video
from shorts_bot.pipeline.moment_finder import find_segments
from shorts_bot.pipeline.renderer import render_short
from shorts_bot.pipeline.transcriber import transcribe
from shorts_bot.worker.celery_app import celery_app


@celery_app.task(bind=True, autoretry_for=(OSError,), retry_backoff=True, max_retries=2)
def process_video(self, source_type: str, source: str, min_duration: int, max_duration: int,
                  chat_id: int, video_format: str = "9:16") -> dict[str, list[str]]:
    settings = get_settings()
    asyncio.run(initialize_database())
    job_dir = settings.media_root / "jobs" / self.request.id
    job_dir.mkdir(parents=True, exist_ok=True)
    try:
        _set_status(self, "DOWNLOADING")
        video = download_video(source, job_dir / "source.mp4") if source_type == "url" else Path(source)
        if not video.exists():
            raise FileNotFoundError(video)

        _set_status(self, "TRANSCRIBING")
        words = transcribe(video, settings.whisper_model)
        _set_status(self, "ANALYZING")
        segments = find_segments(
            words, min_duration, max_duration, settings.llm_api_key, settings.llm_base_url,
            settings.llm_model, settings.llm_api_style,
        )

        outputs: list[str] = []
        banner = asyncio.run(get_banner())
        banner_path = Path(banner.file_path) if banner and banner.enabled and banner.file_path else None
        _set_status(self, "RENDERING")
        for index, segment in enumerate(segments, start=1):
            output = render_short(
                video, words, segment, job_dir / f"short_{index}.mp4", video_format, banner_path
            )
            outputs.append(str(output))
            asyncio.run(update_job(self.request.id, "RENDERING", current=index, total=len(segments)))
        _set_status(self, "DELIVERING")
        asyncio.run(_deliver(chat_id, outputs))
        _set_status(self, "DONE")
        asyncio.run(update_job(self.request.id, "COMPLETED", outputs=outputs))
        return {"outputs": outputs}
    except Exception as error:
        asyncio.run(update_job(self.request.id, "FAILED", error=str(error)))
        raise


def _set_status(task, status: str) -> None:
    task.update_state(state=status)
    asyncio.run(update_job(task.request.id, status))


async def _deliver(chat_id: int, outputs: list[str]) -> None:
    bot = Bot(get_settings().telegram_bot_token)
    try:
        for path in outputs:
            from aiogram.types import FSInputFile
            await bot.send_video(chat_id, FSInputFile(path), caption="Готовый ролик")
    finally:
        await bot.session.close()
