"""Every AI call (ADR-058 items 1-4): the module must be on, the distributor under its monthly
units (⚙ ``platform.ai_monthly_units``), the provider quick enough
(⚙ ``platform.ai_timeout_seconds``); each call is recorded in ``AiUsage`` (never the text).
Anything else returns ``None`` and the caller works as without AI."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from apps.ai.adapters.base import AiProviderError, Embedded, EmbeddingProvider
from apps.ai.adapters.mock import MockEmbeddings
from apps.ai.models import AiUsage, ProductEmbedding
from apps.catalog.models import Product
from apps.platform.selectors import get_platform_setting, is_feature_enabled
from common.dates import to_ist
from common.tenancy import require_tenant_id

log = logging.getLogger(__name__)
FLAG = "ai"


def embedder() -> EmbeddingProvider:
    """The configured provider (``AI_EMBEDDINGS_PROVIDER``; ``mock`` unless set)."""
    name = getattr(settings, "AI_EMBEDDINGS_PROVIDER", "mock")
    if name == "mock":
        return MockEmbeddings()
    # TODO(verify): choose a multilingual embedding provider (Hindi/English mix) and implement
    # its adapter from the provider's official API docs and pricing (pre-production item 38).
    raise AiProviderError(f"embedding provider {name!r} isn't set up")


def enabled(tenant_id: UUID) -> bool:
    return bool(is_feature_enabled(FLAG, tenant_id))


def month_start(now: datetime | None = None) -> datetime:
    local = to_ist(now or timezone.now())
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def units_this_month(tenant_id: UUID) -> int:
    totals = AiUsage.objects.filter(tenant_id=tenant_id, created_at__gte=month_start()).aggregate(
        units_in=Sum("units_in"), units_out=Sum("units_out")
    )
    return int(totals["units_in"] or 0) + int(totals["units_out"] or 0)


def within_limit(tenant_id: UUID) -> bool:
    limit = int(get_platform_setting("platform.ai_monthly_units") or 0)
    return limit <= 0 or units_this_month(tenant_id) < limit


def embed(texts: list[str], *, feature: str) -> Embedded | None:
    """Vectors for ``texts`` for the active distributor, or ``None`` (off, over the limit, or the
    provider failed: the caller falls back)."""
    tenant = require_tenant_id()
    if not texts or not enabled(tenant) or not within_limit(tenant):
        return None
    timeout = float(get_platform_setting("platform.ai_timeout_seconds") or 5)
    started = time.monotonic()
    try:
        provider = embedder()
        result = provider.embed(texts, timeout=timeout)
    except Exception as exc:  # any provider trouble: record it and step aside
        name = getattr(settings, "AI_EMBEDDINGS_PROVIDER", "mock")
        AiUsage.objects.create(
            feature=feature,
            provider=str(name),
            duration_ms=int((time.monotonic() - started) * 1000),
            ok=False,
            error=str(exc)[:200],
        )
        log.warning("ai embeddings failed", extra={"feature": feature, "error": str(exc)[:200]})
        return None
    AiUsage.objects.create(
        feature=feature,
        provider=provider.name,
        model=result.model,
        units_in=result.units,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return result


# --- Product embeddings -------------------------------------------------------------------------


def product_text(product: Product) -> str:
    """What a product's meaning is made from: name, code, brand, category path, tags and the
    description."""
    from apps.catalog.selectors import ancestor_ids

    parts = [product.name, product.code]
    if product.brand is not None:
        parts.append(product.brand.name)
    if product.category_id:
        from apps.catalog.models import Category

        chain = ancestor_ids(product.category_id)
        names = dict(Category.objects.filter(pk__in=chain).values_list("pk", "name"))
        parts.extend(names[pk] for pk in reversed(chain) if pk in names)
    parts.extend(product.tags or [])
    if product.description:
        parts.append(product.description[:500])
    return " · ".join(p for p in parts if p)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


BATCH = 64


def refresh_embeddings(product_ids: Iterable[UUID] | None = None) -> int:
    """Make or remake the active distributor's product embeddings whose text changed (all live
    products, or ``product_ids``); returns how many were written. Stops quietly when AI steps
    aside."""
    tenant = require_tenant_id()
    if not enabled(tenant):
        return 0
    qs = Product.objects.filter(deleted_at__isnull=True).select_related("brand")
    if product_ids is not None:
        qs = qs.filter(pk__in=list(product_ids))
    known = dict(ProductEmbedding.objects.values_list("product_id", "source_hash"))
    pending = []
    for product in qs.order_by("pk"):
        text = product_text(product)
        digest = _hash(text)
        if known.get(product.pk) != digest:
            pending.append((product, text, digest))
    written = 0
    for start in range(0, len(pending), BATCH):
        chunk = pending[start : start + BATCH]
        result = embed([text for _, text, _ in chunk], feature=AiUsage.Feature.SEARCH_INDEX)
        if result is None:
            break
        for (product, _, digest), vector in zip(chunk, result.vectors, strict=True):
            ProductEmbedding.objects.update_or_create(
                product=product,
                defaults={"vector": vector, "source_hash": digest, "model": result.model},
            )
            written += 1
    return written


QUEUE_DELAY_SECONDS = 30  # lets an import or a bulk change finish first


def queue_embeddings() -> None:
    """After product changes: one background refresh per distributor within the delay (the task
    remakes only what changed). Nothing while the module is off."""
    from django.core.cache import cache
    from django.db import transaction

    tenant = require_tenant_id()
    if not enabled(tenant) or not cache.add(f"ai-embed-queued:{tenant}", 1, QUEUE_DELAY_SECONDS):
        return

    def send() -> None:
        from apps.ai.tasks import embed_products

        embed_products.apply_async(kwargs={"tenant_id": str(tenant)}, countdown=QUEUE_DELAY_SECONDS)

    transaction.on_commit(send)
