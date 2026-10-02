"""Import work in the background (thin: calls services)."""

from typing import Any

from celery import shared_task

from common.languages import speaking
from common.task_base import TenantTask
from common.tenancy import require_tenant_id


@shared_task(name="dataio.validate_import", base=TenantTask, bind=True, atomic=False, max_retries=3)
def validate_import(self: Any, *, job_id: str, tenant_id: str) -> None:
    from apps.dataio import services

    # Messages are stored to show later: in the language of the person who uploaded the file.
    with speaking(services.job_person(job_id), require_tenant_id()):
        try:
            services.validate_job(job_id)
        except Exception as exc:
            if self.request.retries >= self.max_retries:
                services.mark_failed(job_id, while_committing=False)
                raise
            raise self.retry(exc=exc, countdown=15 * 2**self.request.retries) from exc


@shared_task(name="dataio.commit_import", base=TenantTask, bind=True, atomic=False, max_retries=3)
def commit_import(self: Any, *, job_id: str, tenant_id: str) -> None:
    """Safe to retry: the file is re-checked first, so rows already applied show as "no change"
    (or as existing, in add-only mode) and are not applied twice."""
    from apps.dataio import services

    with speaking(services.job_person(job_id), require_tenant_id()):
        try:
            services.commit_job(job_id)
        except Exception as exc:
            if self.request.retries >= self.max_retries:
                services.mark_failed(job_id, while_committing=True)
                raise
            raise self.retry(exc=exc, countdown=30 * 2**self.request.retries) from exc
