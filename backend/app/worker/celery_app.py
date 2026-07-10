from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "revora_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)

# Load task modules
celery_app.autodiscover_tasks(["app.worker.tasks"])
