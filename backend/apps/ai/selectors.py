"""AI use this month (ADR-058 item 2, ADR-059 item 8): a distributor's own, and every
distributor's for the super admin (through the audited platform alias). Kept in the provider's
units; shown as estimated rupees, assistant questions and shop searches (``pricing``)."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from django.db.models import Count, Q, QuerySet, Sum

from apps.ai import pricing
from apps.ai.models import AiUsage, AssistantQuestion
from apps.ai.services import FLAG, month_start
from apps.platform.models import Tenant
from apps.platform.selectors import get_platform_setting, is_feature_enabled
from common.platform_db import platform_db
from common.tenancy import require_tenant_id

NEAR = 0.9  # "near the limit" from 90% of it, as for plan limits


def monthly_limit() -> int | None:
    """⚙ ``platform.ai_monthly_units``; ``None`` when there is no limit (0)."""
    limit = int(get_platform_setting("platform.ai_monthly_units") or 0)
    return limit if limit > 0 else None


def _totals(qs: QuerySet[Any, dict[str, Any]]) -> Any:
    return qs.annotate(
        calls=Count("pk"),
        failed=Count("pk", filter=Q(ok=False)),
        units_in=Sum("units_in"),
        units_out=Sum("units_out"),
    )


def _units(row: dict[str, Any]) -> int:
    return int(row["units_in"] or 0) + int(row["units_out"] or 0)


def _cost(rows: list[dict[str, Any]], p: pricing.Prices) -> Decimal:
    return sum(
        (p.cost(r["feature"], int(r["units_in"] or 0), int(r["units_out"] or 0)) for r in rows),
        Decimal(0),
    )


def _searches(rows: list[dict[str, Any]]) -> int:
    return sum(r["calls"] - r["failed"] for r in rows if r["feature"] == "SEARCH_QUERY")


def _allowance(limit: int | None, p: pricing.Prices) -> dict[str, Any] | None:
    found = pricing.allowance(limit, p)
    if found is None:
        return None
    return {"questions": found.questions, "searches": found.searches, "cost": found.cost}


def my_usage() -> dict[str, Any]:
    """The active distributor's AI use this month: estimated rupees, questions and searches, in
    total and by feature, against the monthly allowance."""
    tenant = require_tenant_id()
    since = month_start()
    rows = list(
        _totals(
            AiUsage.objects.filter(created_at__gte=since).values("feature").order_by()
        ).order_by("feature")
    )
    p = pricing.prices()
    limit = monthly_limit()
    units = sum(_units(r) for r in rows)
    return {
        "enabled": bool(is_feature_enabled(FLAG, tenant)),
        "since": since.date(),
        "model": p.model,
        "cost": pricing.rupees(_cost(rows, p)),
        "questions": AssistantQuestion.objects.filter(created_at__gte=since).count(),
        "searches": _searches(rows),
        "allowance": _allowance(limit, p),
        "units": units,
        "limit": limit,
        "calls": sum(r["calls"] for r in rows),
        "failed": sum(r["failed"] for r in rows),
        "near_limit": bool(limit and units >= limit * NEAR),
        "by_feature": [
            {
                "feature": r["feature"],
                "cost": pricing.rupees(_cost([r], p)),
                "units": _units(r),
                "calls": r["calls"],
                "failed": r["failed"],
            }
            for r in rows
        ],
    }


def platform_usage(alias: str | None = None) -> dict[str, Any]:
    """Every distributor that used AI this month, the dearest first, and what the cap comes to
    (platform alias)."""
    alias = alias or platform_db("platform.ai_usage")
    since = month_start()
    per_feature = list(
        _totals(
            AiUsage.objects.unscoped()
            .using(alias)
            .filter(created_at__gte=since)
            .values("tenant_id", "feature")
            .order_by()
        )
    )
    by_tenant: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in per_feature:
        by_tenant[row["tenant_id"]].append(row)
    questions = dict(
        AssistantQuestion.objects.unscoped()
        .using(alias)
        .filter(created_at__gte=since)
        .values("tenant_id")
        .annotate(n=Count("pk"))
        .values_list("tenant_id", "n")
        .order_by()
    )
    names = dict(Tenant.objects.using(alias).filter(pk__in=by_tenant).values_list("id", "name"))
    p = pricing.prices()
    limit = monthly_limit()
    allowance = _allowance(limit, p)
    result = []
    for tenant_id, rows in by_tenant.items():
        units = sum(_units(r) for r in rows)
        result.append(
            {
                "tenant_id": tenant_id,
                "name": names.get(tenant_id, ""),
                "cost": pricing.rupees(_cost(rows, p)),
                "questions": questions.get(tenant_id, 0),
                "searches": _searches(rows),
                "units": units,
                "calls": sum(r["calls"] for r in rows),
                "failed": sum(r["failed"] for r in rows),
                "near_limit": bool(limit and units >= limit * NEAR),
            }
        )
    result.sort(key=lambda r: (-r["cost"], -r["units"], r["name"]))
    return {"model": p.model, "limit": limit, "allowance": allowance, "rows": result}
