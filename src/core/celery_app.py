"""Celery global application configuration."""

import structlog
from celery import Celery
from src.config import settings

logger = structlog.get_logger()

# Define Celery app
celery_app = Celery(
    "agentdeep",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=1800,  # 30 minutes max execution time for agent tasks
)

# Auto-discover tasks from celery_tasks module
celery_app.autodiscover_tasks(["src.core"], related_name="celery_tasks")

# Explicit import to ensure registration on startup
try:
    import src.core.celery_tasks
    import src.core.celery_monitoring
except ImportError:
    pass

logger.info(
    "Initialized Celery Application",
    broker=settings.celery_broker_url,
    enabled=settings.celery_enabled,
)
