"""Catalog background work (thin: calls services)."""

from typing import Any

from celery import shared_task

from common.task_base import TenantTask


@shared_task(
    name="catalog.process_product_image",
    base=TenantTask,
    bind=True,
    atomic=False,  # no DB transaction is held while images are resized and uploaded
    max_retries=5,
)
def process_product_image(self: Any, *, image_id: str, tenant_id: str) -> None:
    """Storage hiccups are retried with backoff; after the last try the image shows as failed so
    the distributor can upload it again."""
    from apps.catalog import services

    try:
        services.process_image(image_id)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            services.mark_image_failed(image_id)
            raise
        raise self.retry(exc=exc, countdown=min(600, 10 * 2**self.request.retries)) from exc


@shared_task(
    name="catalog.delete_image_objects",
    autoretry_for=(Exception,),
    retry_backoff=30,
    max_retries=5,
)
def delete_image_objects(*, original_key: str, public_keys: list[str]) -> None:
    """Remove a deleted image's files after commit (a failure only leaves unreferenced files)."""
    from common.storage import get_storage

    storage = get_storage()
    if original_key:
        storage.delete(original_key)
    for key in public_keys:
        storage.delete_public(key)
