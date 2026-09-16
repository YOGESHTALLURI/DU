from celery import Celery
from backend.core.config import settings

celery_app = Celery(
    "cinqflow",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

@celery_app.task(name="pipeline.execute_batch")
def execute_batch(batch_id: str):
    """Execute a pipeline batch. Implemented in Phase 7."""
    # Placeholder — real implementation in Phase 7
    raise NotImplementedError("Pipeline execution implemented in Phase 7")