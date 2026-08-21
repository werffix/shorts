import json

from sqlalchemy import update

from shorts_bot.db.models import VideoJob
from shorts_bot.db.session import SessionLocal


async def create_job(
    job_id: str, chat_id: int, source_type: str, source: str, min_duration: int, max_duration: int
) -> None:
    async with SessionLocal() as session:
        session.add(VideoJob(
            id=job_id, chat_id=chat_id, source_type=source_type, source=source,
            min_duration=min_duration, max_duration=max_duration,
        ))
        await session.commit()


async def update_job(job_id: str, status: str, outputs: list[str] | None = None, error: str | None = None) -> None:
    values: dict[str, str | None] = {"status": status, "error": error}
    if outputs is not None:
        values["result_paths"] = json.dumps(outputs)
    async with SessionLocal() as session:
        await session.execute(update(VideoJob).where(VideoJob.id == job_id).values(**values))
        await session.commit()
