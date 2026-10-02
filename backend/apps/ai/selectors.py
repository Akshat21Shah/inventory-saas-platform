"""AI use this month (ADR-058 item 2): a distributor's own, and every distributor's for the super
admin (through the audited platform alias)."""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Q, QuerySet, Sum

from apps.ai.models import AiUsage
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
        units=Sum("units_in") + Sum("units_out"),
    )


def my_usage() -> dict[str, Any]:
    """The active distributor's AI use this month, in total and by feature."""
    tenant = require_tenant_id()
    rows = list(
        _totals(
            AiUsage.objects.filter(created_at__gte=month_start()).values("feature").order_by()
        ).order_by("feature")
    )
    limit = monthly_limit()
    units = sum(int(r["units"] or 0) for r in rows)
    return {
        "enabled": bool(is_feature_enabled(FLAG, tenant)),
        "since": month_start().date(),
        "units": units,
        "limit": limit,
        "calls": sum(r["calls"] for r in rows),
        "failed": sum(r["failed"] for r in rows),
        "near_limit": bool(limit and units >= limit * NEAR),
        "by_feature": [
            {
                "feature": r["feature"],
                "units": int(r["units"] or 0),
                "calls": r["calls"],
                "failed": r["failed"],
            }
            for r in rows
        ],
    }


def usage_by_tenant(alias: str | None = None) -> list[dict[str, Any]]:
    """Every distributor that used AI this month, the heaviest first (platform alias)."""
    alias = alias or platform_db("platform.ai_usage")
    rows = list(
        _totals(
            AiUsage.objects.unscoped()
            .using(alias)
            .filter(created_at__gte=month_start())
            .values("tenant_id")
            .order_by()
        )
    )
    names = dict(
        Tenant.objects.using(alias)
        .filter(pk__in=[r["tenant_id"] for r in rows])
        .values_list("id", "name")
    )
    limit = monthly_limit()
    result = [
        {
            "tenant_id": r["tenant_id"],
            "name": names.get(r["tenant_id"], ""),
            "units": int(r["units"] or 0),
            "calls": r["calls"],
            "failed": r["failed"],
            "limit": limit,
            "near_limit": bool(limit and int(r["units"] or 0) >= limit * NEAR),
        }
        for r in rows
    ]
    return sorted(result, key=lambda r: (-r["units"], r["name"]))
