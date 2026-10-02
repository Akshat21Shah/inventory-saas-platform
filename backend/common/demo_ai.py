"""AI demo data (ADR-058, 9d.5). DEBUG only (called from the seed commands).

- Demo (``seed_demo_ai``): Sharma Distributors gets the ``ai`` module and its products' meanings
  (the local mock), so a shop's misspelt search finds products, and its owner three answered
  questions to the data assistant (ADR-059).
- Volume (``seed_volume_ai``): the ``ai`` module and product meanings for a test distributor, and a
  busy month of shop searches, all within the current month, so the usage pages are timed at their
  worst (the month's end).
"""

from __future__ import annotations

import random
from datetime import timedelta

from django.utils import timezone

from apps.ai import services as ai
from apps.ai.models import AiUsage
from apps.platform.models import FeatureFlag, Tenant, TenantFeature
from apps.platform.selectors import invalidate_tenant_features
from common.tenancy import tenant_context

DEMO_WITH_AI = ("sharma",)
DEMO_QUESTIONS = (
    "Which shops haven't ordered in 30 days?",
    "What are our top 5 products this month?",
    "Who owes us the most money?",
)


def _module_on(tenant: Tenant) -> None:
    TenantFeature.objects.update_or_create(
        flag=FeatureFlag.objects.get(code=ai.FLAG), defaults={"enabled": True}
    )
    invalidate_tenant_features(tenant.pk)


def seed_demo_ai(tenant: Tenant) -> bool:
    """Inside ``tenant_context``; returns whether AI is on for this distributor."""
    if tenant.slug not in DEMO_WITH_AI:
        return False
    _module_on(tenant)
    ai.refresh_embeddings()
    _demo_questions(tenant)
    return True


def _demo_questions(tenant: Tenant) -> None:
    from apps.accounts.models import User
    from apps.ai.assistant import service
    from apps.ai.models import AssistantQuestion

    owner = User.objects.filter(email=f"owner@{tenant.slug}.example.com").first()
    if owner is None or AssistantQuestion.objects.filter(user=owner).exists():
        return
    for question in DEMO_QUESTIONS:
        asked = AssistantQuestion.objects.create(user=owner, question=question)
        service.answer(asked.pk)


def seed_volume_ai(tenant: Tenant, *, searches: int = 60_000, seed: int = 13) -> int | None:
    """The module on, every product's meaning, and ``searches`` shop searches' usage rows within
    the current month; ``None`` when the distributor already has search rows."""
    rng = random.Random(f"{tenant.slug}:ai:{seed}")  # noqa: S311 - demo data
    with tenant_context(tenant.pk):
        if AiUsage.objects.filter(feature=AiUsage.Feature.SEARCH_QUERY).exists():
            return None
        _module_on(tenant)
        ai.refresh_embeddings()
        start, now = ai.month_start(), timezone.now()
        span = max(int((now - start).total_seconds()), 1)
        rows = [
            AiUsage(
                tenant_id=tenant.pk,
                feature=AiUsage.Feature.SEARCH_QUERY,
                provider="mock",
                model="mock-trigram-256",
                units_in=rng.randint(4, 30),
                duration_ms=rng.randint(1, 40),
                ok=rng.random() > 0.002,
            )
            for _ in range(searches)
        ]
        made = AiUsage.objects.bulk_create(rows, batch_size=5_000)
        # Spread over the month so far (``created_at`` is set on insert).
        for row in made:
            row.created_at = start + timedelta(seconds=rng.randint(0, span))
        AiUsage.objects.bulk_update(made, ["created_at"], batch_size=5_000)
        return len(made)
