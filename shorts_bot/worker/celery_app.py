from celery import Celery

from shorts_bot.config import get_settings

settings = get_settings()
celery_app = Celery(
    "shorts_bot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["shorts_bot.worker.tasks"],
)
celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)
