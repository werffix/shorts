from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class VideoJob(Base):
    __tablename__ = "video_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    source_type: Mapped[str] = mapped_column(String(8))
    source: Mapped[str] = mapped_column(Text)
    min_duration: Mapped[int] = mapped_column(Integer)
    max_duration: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", index=True)
    result_paths: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
