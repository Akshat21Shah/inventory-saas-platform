"""Celery tasks for the platform app."""

from celery import shared_task

from common.storage import get_storage


@shared_task(
    name="platform.delete_stored_object",
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_backoff_max=3600,
    max_retries=6,
)
def delete_stored_object(key: str) -> None:
    """Remove a replaced or removed file from object storage."""
    get_storage().delete(key)
