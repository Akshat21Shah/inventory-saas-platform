"""Shop self-service demo data (ADR-057, 9c.5): one return request from Ganesh Kirana waiting for
Sharma Distributors' decision, so the screens have something to show. Idempotent; DEBUG only
(called from the seed command). The delivery code and bounce charge stay at their defaults (off)."""

from __future__ import annotations

from decimal import Decimal

from apps.accounts.models import User
from apps.billing import returns
from apps.billing.models import DocumentStatus, Invoice, ReturnRequest
from apps.platform.models import Tenant
from apps.retailers.models import Retailer

DEMO_WITH_A_RETURN = ("sharma",)
SHOP_PHONE = "+919876500001"  # Ganesh Kirana


def seed_demo_returns(tenant: Tenant) -> bool:
    """Inside ``tenant_context``; returns whether a request is waiting."""
    if tenant.slug not in DEMO_WITH_A_RETURN:
        return False
    if ReturnRequest.objects.exists():
        return True
    shop = Retailer.objects.filter(mobile=SHOP_PHONE).first()
    login = User.objects.filter(tenant=tenant, phone=SHOP_PHONE).first()
    if shop is None or login is None:
        return False
    for invoice in Invoice.objects.filter(retailer=shop, status=DocumentStatus.ISSUED).order_by(
        "-invoice_date", "-created_at"
    ):
        if not returns.can_request(invoice):
            continue
        left = returns.returnable(list(invoice.lines.all()))
        line_id = next((pk for pk, qty in left.items() if qty >= 1), None)
        if line_id is None:
            continue
        returns.request_return(
            invoice.pk,
            [returns.AskedLine(line_id, Decimal("1"))],
            reason="DAMAGED",
            note="Two packets were torn when they arrived.",
            by=login,
            retailer_id=shop.pk,
        )
        return True
    return False


def seed_volume_returns(tenant: Tenant, *, count: int = 300, seed: int = 11) -> int | None:
    """Speed-check data: ``count`` return requests on random bills of the year (a third still
    waiting, the rest rejected, so no credit notes or stock change). Bulk-inserted like the rest
    of the volume data; ``None`` when the distributor already has requests."""
    import random

    from django.utils import timezone

    from apps.billing.models import InvoiceLine, ReturnRequestLine
    from common.models import Sequence
    from common.tenancy import tenant_context

    rng = random.Random(f"{tenant.slug}:returns:{seed}")  # noqa: S311 - demo data
    with tenant_context(tenant.pk):
        if ReturnRequest.objects.exists():
            return None
        lines = list(
            InvoiceLine.objects.filter(invoice__status=DocumentStatus.ISSUED)
            .select_related("invoice")
            .order_by("?")[:count]
        )
        owner = User.objects.filter(email=f"owner@{tenant.slug}.example.com").first()
        if owner is None or not lines:
            return 0
        year = timezone.localdate().year
        requests, request_lines = [], []
        for number, line in enumerate(lines, start=1):
            waiting = number % 3 == 0
            request = ReturnRequest(
                tenant_id=tenant.pk,
                number=f"RR-{year}-{number:06d}",
                retailer_id=line.invoice.retailer_id,
                invoice_id=line.invoice_id,
                status=ReturnRequest.Status.REQUESTED if waiting else ReturnRequest.Status.REJECTED,
                reason=rng.choice(("DAMAGED", "EXPIRED", "WRONG_ITEM", "EXCESS_SUPPLY")),
                requested_by=owner,
                decided_by=None if waiting else owner,
                decided_at=None if waiting else timezone.now(),
                decision_note="" if waiting else "Checked with the shop: kept.",
                created_by=owner,
            )
            requests.append(request)
            request_lines.append(
                ReturnRequestLine(
                    tenant_id=tenant.pk,
                    request=request,
                    invoice_line=line,
                    quantity=min(Decimal(line.quantity), Decimal("1")),
                    created_by=owner,
                )
            )
        ReturnRequest.objects.bulk_create(requests, batch_size=1000)
        ReturnRequestLine.objects.bulk_create(request_lines, batch_size=1000)
        Sequence.objects.update_or_create(
            name="RETURN_REQUEST", period=str(year), defaults={"next_value": len(requests) + 1}
        )
        return len(requests)
