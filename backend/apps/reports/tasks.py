"""Report tasks (ADR-050): exports on the ``reports`` queue, so they never delay messages or
IRNs; expired files are removed every hour."""

from uuid import UUID

from celery import shared_task

from common.task_base import TenantTask


# Large exports may take longer than the default limit (CELERY_TASK_TIME_LIMIT).
@shared_task(
    name="reports.build_run", base=TenantTask, atomic=False, time_limit=900, soft_time_limit=840
)
def build_run(*, run_id: str, tenant_id: str) -> str:
    from apps.reports import services

    return services.make_run(UUID(run_id))


@shared_task(name="reports.expire_runs")
def expire_runs() -> int:
    from apps.reports import services

    return services.expire_due()
