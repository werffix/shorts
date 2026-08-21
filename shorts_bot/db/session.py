import asyncio

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shorts_bot.config import get_settings
from shorts_bot.db.models import Base

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def initialize_database(retries: int = 30, delay: float = 2.0) -> None:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            return
        except Exception as error:
            last_error = error
            if attempt == retries:
                raise
            print(f"Database is not ready (attempt {attempt}/{retries}): {error}", flush=True)
            await asyncio.sleep(delay)
    if last_error:
        raise last_error


async def session_scope() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
