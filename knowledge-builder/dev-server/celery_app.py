import os
from celery import Celery
from dotenv import load_dotenv

from advandeb_kb.config.settings import settings

load_dotenv()

celery_app = Celery(
    "advandeb_knowledge_builder",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)


@celery_app.task
def health_check() -> str:
    """Simple task to verify Celery/Redis wiring."""
    return "ok"
