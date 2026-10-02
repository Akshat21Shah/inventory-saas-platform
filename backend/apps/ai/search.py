"""Semantic product search (ADR-058 item 3): after today's keyword matches, the products nearest
in meaning to what was typed, among those the caller may show. Nothing when AI steps aside."""

from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from django.db.models import F, QuerySet, Value
from django.db.models.functions import Cast

from apps.ai import services
from apps.ai.adapters.base import DIMENSIONS
from apps.ai.models import AiUsage, ProductEmbedding
from apps.catalog.models import Product
from apps.platform.selectors import get_platform_setting
from common.tenancy import require_tenant_id
from common.vectors import CosineDistance, VectorField, literal


def nearest(
    qs: QuerySet[Product], text: str, *, exclude: Collection[UUID], limit: int
) -> list[Product]:
    """Up to ``limit`` products of ``qs`` (already filtered for what may be shown) closest in
    meaning to ``text``, closest first, not in ``exclude``."""
    text = " ".join(text.split())[:100]
    tenant = require_tenant_id()
    if limit <= 0 or not text or not services.enabled(tenant):
        return []
    if not ProductEmbedding.objects.exists():
        return []
    found = services.embed([text], feature=AiUsage.Feature.SEARCH_QUERY)
    if not found:
        return []
    least = int(get_platform_setting("platform.ai_search_min_similarity_percent") or 35) / 100
    query = Cast(Value(literal(found.vectors[0])), output_field=VectorField(dimensions=DIMENSIONS))
    distance = CosineDistance(F("ai_embedding__vector"), query)
    # Rank on the bare query first: with the caller's joins (brand, unit, …) the planner
    # misjudges the row count and the search gets several times slower.
    ids = list(
        qs.select_related(None)
        .prefetch_related(None)
        .exclude(pk__in=list(exclude))
        .filter(ai_embedding__isnull=False)
        .annotate(distance=distance)
        .filter(distance__lte=1 - least)
        .order_by("distance", "name", "id")
        .values_list("pk", flat=True)[:limit]
    )
    by_id = {p.pk: p for p in qs.filter(pk__in=ids)}
    return [by_id[pk] for pk in ids if pk in by_id]
