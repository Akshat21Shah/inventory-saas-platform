"""Product embeddings in the background (ADR-058 item 3): when a product's text changes, and
nightly for anything missed, for distributors with the module on; the assistant's answers
(ADR-059). Thin: they call the services."""

from celery import shared_task

from common.task_base import TenantTask


@shared_task(name="ai.embed_products", base=TenantTask)
def embed_products(*, tenant_id: str, product_ids: list[str] | None = None) -> int:
    """One distributor's products whose text changed (all, or these). Returns how many."""
    from uuid import UUID

    from apps.ai import services

    ids = [UUID(pk) for pk in product_ids] if product_ids is not None else None
    return services.refresh_embeddings(ids)


@shared_task(name="ai.embed_all")
def embed_all() -> int:
    """Nightly, 02:15 IST: every distributor with the module on."""
    from apps.ai import services
    from apps.platform.models import Tenant

    tenants = [
        tenant_id
        for tenant_id in Tenant.objects.exclude(status=Tenant.Status.SUSPENDED).values_list(
            "pk", flat=True
        )
        if services.enabled(tenant_id)
    ]
    for tenant_id in tenants:
        embed_products.apply_async(kwargs={"tenant_id": str(tenant_id)})
    return len(tenants)


@shared_task(name="ai.answer_question", base=TenantTask)
def answer_question(*, tenant_id: str, question_id: str) -> str:
    """Answer one waiting question (the provider calls have their own timeout and retry)."""
    from uuid import UUID

    from apps.ai.assistant import service

    return str(service.answer(UUID(question_id)).status)
