import json

from sqlalchemy import delete, func, select, update

from shorts_bot.db.models import BannerConfig, User, VideoJob
from shorts_bot.db.session import SessionLocal


async def create_job(
    job_id: str, chat_id: int, source_type: str, source: str, min_duration: int, max_duration: int,
    video_format: str, status_message_id: int | None = None,
) -> None:
    async with SessionLocal() as session:
        session.add(VideoJob(
            id=job_id, chat_id=chat_id, source_type=source_type, source=source,
            min_duration=min_duration, max_duration=max_duration, video_format=video_format,
            status_message_id=status_message_id, status_chat_id=chat_id,
        ))
        await session.commit()


async def update_job(job_id: str, status: str, outputs: list[str] | None = None, error: str | None = None,
                     current: int | None = None, total: int | None = None) -> None:
    values: dict[str, object] = {"status": status, "error": error}
    if outputs is not None:
        values["result_paths"] = json.dumps(outputs)
    if current is not None:
        values["progress_current"] = current
    if total is not None:
        values["progress_total"] = total
    async with SessionLocal() as session:
        await session.execute(update(VideoJob).where(VideoJob.id == job_id).values(**values))
        await session.commit()


async def get_job(job_id: str) -> VideoJob | None:
    async with SessionLocal() as session:
        return await session.scalar(select(VideoJob).where(VideoJob.id == job_id))


async def is_allowed(telegram_id: int, admin_id: int) -> bool:
    if telegram_id == admin_id:
        return True
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id, User.is_active.is_(True)))
        return user is not None


async def list_users() -> list[User]:
    async with SessionLocal() as session:
        return list((await session.scalars(select(User).where(User.is_active.is_(True)).order_by(User.added_at))).all())


async def get_user_details(telegram_id: int) -> tuple[User | None, int]:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        jobs_count = await session.scalar(select(func.count(VideoJob.id)).where(VideoJob.chat_id == telegram_id))
        return user, int(jobs_count or 0)


async def add_user(telegram_id: int, username: str | None, added_by: int) -> None:
    async with SessionLocal() as session:
        existing = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if existing:
            existing.username = username or existing.username
            existing.is_active = True
        else:
            session.add(User(telegram_id=telegram_id, username=username, added_by=added_by))
        await session.commit()


async def remove_user(telegram_id: int) -> None:
    async with SessionLocal() as session:
        await session.execute(update(User).where(User.telegram_id == telegram_id).values(is_active=False))
        await session.commit()


async def get_banner() -> BannerConfig | None:
    async with SessionLocal() as session:
        return await session.scalar(select(BannerConfig).where(BannerConfig.id == 1))


async def save_banner(path: str, uploaded_by: int) -> None:
    async with SessionLocal() as session:
        banner = await session.get(BannerConfig, 1)
        if banner is None:
            banner = BannerConfig(id=1)
            session.add(banner)
        banner.file_path, banner.enabled, banner.uploaded_by = path, True, uploaded_by
        await session.commit()


async def set_banner_enabled(enabled: bool) -> None:
    async with SessionLocal() as session:
        await session.execute(update(BannerConfig).where(BannerConfig.id == 1).values(enabled=enabled))
        await session.commit()
