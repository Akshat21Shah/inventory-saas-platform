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
