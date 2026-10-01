"""The super admin's dashboard (ADR-050 item 12): platform health across distributors. Every
query runs on the audited platform alias (``platform_db``), since distributor rows are protected
by row-level security."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, OuterRef, Subquery, Sum
from django.db.models.functions import TruncDay
from django.utils import timezone

from apps.accounts.models import Membership
from apps.catalog.models import Product
from apps.compliance.models import EInvoiceRecord, EWayBill, GstCredential
from apps.notifications.models import Notification
from apps.orders.models import Order
from apps.payments.models import GatewayConfig
from apps.platform.models import Subscription, Tenant
from apps.retailers.models import Retailer
from common import metrics
from common.dates import IST, today_ist
from common.platform_db import platform_db

DAYS = 30
FAILURE_DAYS = 7
TOP = 5
NEAR = Decimal("0.9")  # "near the limit" from 90% of it


def orders_per_day(alias: str) -> list[dict[str, Any]]:
    end = today_ist()
    start = end - timedelta(days=DAYS - 1)
    rows = {
        r["day"]: r
        for r in Order.objects.unscoped()
        .using(alias)
        .filter(placed_at__gte=timezone.now() - timedelta(days=DAYS + 1))
        .annotate(day=TruncDay("placed_at", tzinfo=IST))
        .values("day")
        .annotate(count=Count("pk"), value=Sum("grand_total"))
        .order_by()
    }
    by_date = {(k.date() if hasattr(k, "date") else k): v for k, v in rows.items()}
    days = [start + timedelta(days=i) for i in range(DAYS)]
    return [
        {
            "date": day,
            "count": by_date.get(day, {}).get("count", 0),
            "value": Decimal(by_date.get(day, {}).get("value") or 0),
        }
        for day in days
    ]


def top_tenants(alias: str) -> list[dict[str, Any]]:
    rows = (
        Order.objects.unscoped()
        .using(alias)
        .filter(placed_at__gte=timezone.now() - timedelta(days=DAYS))
        .values("tenant_id")
        .annotate(orders=Count("pk"), value=Sum("grand_total"))
        .order_by("-value")[:TOP]
    )
    names = dict(Tenant.objects.using(alias).values_list("id", "name"))
    return [
        {
            "tenant_id": r["tenant_id"],
            "name": names.get(r["tenant_id"], ""),
            "orders": r["orders"],
            "value": r["value"],
        }
        for r in rows
    ]


def _per_tenant(queryset: Any) -> dict[Any, int]:
    return dict(
        queryset.values("tenant_id")
        .annotate(n=Count("pk"))
        .values_list("tenant_id", "n")
        .order_by()
    )


def failures(alias: str) -> list[dict[str, Any]]:
    """Distributors with something failing: messages in the last 7 days, IRNs and e-way bills
    still failed, and a GST provider login or payment gateway that stopped working."""
    since = timezone.now() - timedelta(days=FAILURE_DAYS)
    messages = _per_tenant(
        Notification.objects.unscoped()
        .using(alias)
        .filter(status=Notification.Status.FAILED, created_at__gte=since)
    )
    irns = _per_tenant(
        EInvoiceRecord.objects.unscoped().using(alias).filter(status=EInvoiceRecord.Status.FAILED)
    )
    ewaybills = _per_tenant(
        EWayBill.objects.unscoped()
        .using(alias)
        .filter(status=EWayBill.Status.FAILED)
        .exclude(error_code="INVOICE_CANCELLED")
    )
    gst_logins = set(
        GstCredential.objects.unscoped()
        .using(alias)
        .filter(status=GstCredential.Status.FAILED)
        .values_list("tenant_id", flat=True)
    )
    gateways = set(
        GatewayConfig.objects.unscoped()
        .using(alias)
        .filter(status=GatewayConfig.Status.FAILED)
        .values_list("tenant_id", flat=True)
    )
    tenants = set(messages) | set(irns) | set(ewaybills) | gst_logins | gateways
    names = dict(Tenant.objects.using(alias).filter(pk__in=tenants).values_list("id", "name"))
    rows = [
        {
            "tenant_id": pk,
            "name": names.get(pk, ""),
            "failed_messages": messages.get(pk, 0),
            "failed_irns": irns.get(pk, 0),
            "failed_ewaybills": ewaybills.get(pk, 0),
            "gst_login_failed": pk in gst_logins,
            "gateway_failed": pk in gateways,
        }
        for pk in tenants
    ]
    return sorted(
        rows,
        key=lambda r: (
            -(r["failed_messages"] + r["failed_irns"] + r["failed_ewaybills"]),
            r["name"],
        ),
    )


def usage(alias: str) -> list[dict[str, Any]]:
    """Shops, staff and products of each distributor against its plan's limits (shown even while
    plan enforcement is off)."""
    current = (
        Subscription.objects.unscoped().using(alias).filter(tenant=OuterRef("pk"), is_current=True)
    )
    tenants = (
        Tenant.objects.using(alias)
        .exclude(status=Tenant.Status.SUSPENDED)
        .annotate(
            plan_name=Subquery(current.values("plan__name")[:1]),
            max_retailers=Subquery(current.values("plan__max_retailers")[:1]),
            max_staff=Subquery(current.values("plan__max_staff")[:1]),
            max_products=Subquery(current.values("plan__max_products")[:1]),
        )
        .values("id", "name", "plan_name", "max_retailers", "max_staff", "max_products")
        .order_by("name")
    )
    shops = _per_tenant(
        Retailer.objects.unscoped().using(alias).filter(is_active=True, deleted_at__isnull=True)
    )
    staff = _per_tenant(Membership.objects.unscoped().using(alias).filter(is_active=True))
    products = _per_tenant(
        Product.objects.unscoped().using(alias).filter(is_active=True, deleted_at__isnull=True)
    )
    rows = []
    for t in tenants:
        figures = {
            "shops": (shops.get(t["id"], 0), t["max_retailers"]),
            "staff": (staff.get(t["id"], 0), t["max_staff"]),
            "products": (products.get(t["id"], 0), t["max_products"]),
        }
        near = any(limit and used >= limit * NEAR for used, limit in figures.values())
        rows.append(
            {
                "tenant_id": t["id"],
                "name": t["name"],
                "plan": t["plan_name"] or "",
                **{name: used for name, (used, _limit) in figures.items()},
                **{f"max_{name}": limit for name, (_used, limit) in figures.items()},
                "near_limit": bool(near),
            }
        )
    return sorted(rows, key=lambda r: (not r["near_limit"], r["name"]))


def health() -> dict[str, Any]:
    alias = platform_db("platform.dashboard_health")
    counted = metrics.last_hours(24)
    requests = counted["requests"]
    return {
        "orders_per_day": orders_per_day(alias),
        "top_tenants": top_tenants(alias),
        "failures": failures(alias),
        "usage": usage(alias),
        "errors_24h": {
            "requests": requests,
            "server_errors": counted["errors"],
            "rate": Decimal(counted["errors"] * 100) / requests if requests else None,
        },
    }
