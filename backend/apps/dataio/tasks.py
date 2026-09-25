"""Import work in the background (thin: calls services)."""

from typing import Any

from celery import shared_task

from common.task_base import TenantTask


@shared_task(name="dataio.validate_import", base=TenantTask, bind=True, atomic=False, max_retries=3)
def validate_import(self: Any, *, job_id: str, tenant_id: str) -> None:
    from apps.dataio import services

    try:
        services.validate_job(job_id)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            services.mark_failed(job_id, "We couldn't check this file. Please upload it again.")
            raise
        raise self.retry(exc=exc, countdown=15 * 2**self.request.retries) from exc


@shared_task(name="dataio.commit_import", base=TenantTask, bind=True, atomic=False, max_retries=3)
def commit_import(self: Any, *, job_id: str, tenant_id: str) -> None:
    """Safe to retry: the file is re-checked first, so rows already applied show as "no change"
    (or as existing, in add-only mode) and are not applied twice."""
    from apps.dataio import services

    try:
        services.commit_job(job_id)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            services.mark_failed(
                job_id,
                "The import stopped part-way. Check the imported rows, then upload the "
                "file again: rows already imported will show as unchanged.",
            )
            raise
        raise self.retry(exc=exc, countdown=30 * 2**self.request.retries) from exc
