"""Demo billing for `make seed` (dev only): old bills and an advance, payments in each mode, a
refund, a salesman's collection waiting for handover, and a return credit note, so the Phase 5
screens have data.
Runs once per tenant, after the demo orders are invoiced."""

from datetime import timedelta
from decimal import Decimal

from apps.accounts.models import User
from apps.billing import credit_notes
from apps.billing.credit_notes import ReturnLine
from apps.billing.models import Invoice
from apps.ledger import services as ledger
from apps.payments import services as payments
from apps.payments.models import Payment
from apps.payments.services import PaymentInput, RefundInput
from apps.platform.models import Tenant
from apps.retailers.models import Retailer
from common.dates import today_ist


def seed_billing(tenant: Tenant, owner: User) -> int:
    """Run inside ``tenant_context(tenant.id)``. Returns how many payments it recorded."""
    if Payment.objects.exists():
        return 0
    sales = User.objects.get(email=f"sales@{tenant.slug}.example.com")
    shops = list(
        Retailer.objects.filter(status=Retailer.Status.ACTIVE, deleted_at__isnull=True).order_by(
            "code"
        )
    )
    if len(shops) < 14:
        return 0
    today = today_ist()
    # Books before the platform: one shop owes an old amount (overdue), one paid in advance.
    ledger.post_adjustment(
        shops[11].pk,
        "OPENING_DEBIT",
        Decimal("2450.00"),
        on=today - timedelta(days=45),
        narration="Balance from the old books",
        by=owner,
    )
    ledger.post_adjustment(
        shops[12].pk,
        "OPENING_CREDIT",
        Decimal("1000.00"),
        on=today - timedelta(days=20),
        narration="Advance paid before the switch",
        by=owner,
    )
    invoices = {
        i.retailer_id: i for i in Invoice.objects.order_by("created_at").select_related("retailer")
    }
    first, second = invoices.get(shops[0].pk), invoices.get(shops[1].pk)
    if first is not None:  # paid in full by bank transfer
        payments.record_payment(
            PaymentInput(
                shops[0].pk, first.grand_total, "BANK_TRANSFER", today, reference_no="NEFT00931"
            ),
            by=owner,
        )
        line = first.lines.order_by("line_no").first()
        if line is not None:  # one unit came back damaged in transit
            credit_notes.issue_return(
                first.pk,
                [ReturnLine(line.pk, Decimal("1"), "DAMAGED")],
                reason="DAMAGED",
                note="Carton crushed in transit",
                by=owner,
            )
    if second is not None:  # part paid by UPI
        payments.record_payment(
            PaymentInput(
                shops[1].pk,
                (second.grand_total / 2).quantize(Decimal("1")),
                "UPI",
                today,
                reference_no="UPI4471023",
            ),
            by=owner,
        )
    # A cheque against the old balance, credited on receipt and not yet cleared.
    payments.record_payment(
        PaymentInput(
            shops[11].pk,
            Decimal("1000.00"),
            "CHEQUE",
            today - timedelta(days=2),
            cheque_number="004512",
            bank_name="State Bank of India",
        ),
        by=owner,
    )
    # Part of the advance paid back by bank transfer (ADR-047).
    payments.record_refund(
        RefundInput(
            shops[12].pk, Decimal("200.00"), "BANK_TRANSFER", today, reference_no="NEFT01188"
        ),
        by=owner,
    )
    # The salesman collected cash on his round; not yet handed over.
    payments.collect_payment(
        PaymentInput(shops[11].pk, Decimal("500.00"), "CASH", today, notes="Collected on round"),
        by=sales,
    )
    return Payment.objects.count()
