"""Payments (PLAN §2.12, §4.6, spec 5.12, ADR-017/046). Offline payments in Phase 5; online
gateway payments (Phase 7) add columns, not a new shape. Status changes and every ledger effect go
through the services."""

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from common.fields import MoneyField
from common.models import TenantScopedModel

USER = settings.AUTH_USER_MODEL


class Payment(TenantScopedModel):
    class Mode(models.TextChoices):
        CASH = "CASH", "Cash"
        CHEQUE = "CHEQUE", "Cheque"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"
        UPI = "UPI", "UPI"

    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"  # credited to the shop
        PENDING_CLEARANCE = "PENDING_CLEARANCE", "Waiting for the cheque to clear"  # not credited
        CLEARED = "CLEARED", "Cheque cleared"
        BOUNCED = "BOUNCED", "Cheque bounced"
        REVERSED = "REVERSED", "Reversed"

    class CreditTiming(models.TextChoices):
        ON_RECEIPT = "ON_RECEIPT", "When received"
        ON_CLEARANCE = "ON_CLEARANCE", "When cleared"

    class Handover(models.TextChoices):
        NOT_TRACKED = "NOT_TRACKED", "Not tracked"  # recorded in the office (payments.record)
        WITH_SALESMAN = "WITH_SALESMAN", "With salesman"
        HANDED_OVER = "HANDED_OVER", "Handed over"
        NOT_NEEDED = "NOT_NEEDED", "Nothing to hand over"  # reversed as entered in error

    number = models.CharField(max_length=16)  # receipt number, RCT/26-27/000001
    retailer = models.ForeignKey("retailers.Retailer", on_delete=models.PROTECT, related_name="+")
    amount = MoneyField()
    mode = models.CharField(max_length=13, choices=Mode.choices)
    status = models.CharField(max_length=17, choices=Status.choices)
    credit_timing = models.CharField(
        max_length=12, choices=CreditTiming.choices, default=CreditTiming.ON_RECEIPT
    )  # snapshot of ⚙ payments.cheque_credit_timing for cheques
    payment_date = models.DateField()  # IST
    reference_no = models.CharField(max_length=60, blank=True, default="")  # UTR, UPI ref
    cheque_number = models.CharField(max_length=20, blank=True, default="")
    cheque_date = models.DateField(null=True, blank=True)
    bank_name = models.CharField(max_length=120, blank=True, default="")
    notes = models.CharField(max_length=500, blank=True, default="")
    recorded_by = models.ForeignKey(
        USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    collected_by = models.ForeignKey(
        USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    handover_status = models.CharField(
        max_length=13, choices=Handover.choices, default=Handover.NOT_TRACKED
    )
    handed_over_at = models.DateTimeField(null=True, blank=True)
    handed_over_by = models.ForeignKey(
        USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    credited = models.BooleanField(default=False)  # a PAYMENT ledger entry exists (not reversed)
    cleared_at = models.DateTimeField(null=True, blank=True)
    unapplied_amount = MoneyField(default=0)  # running: credited but not yet matched to invoices
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = models.CharField(max_length=300, blank=True, default="")
    receipt_pdf_key = models.CharField(max_length=255, blank=True, default="")
    receipt_pdf_status = models.CharField(max_length=8, default="PENDING")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="uniq_payment_number"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_pos"),
            models.CheckConstraint(
                condition=Q(unapplied_amount__gte=0) & Q(unapplied_amount__lte=F("amount")),
                name="payment_unapplied",
            ),
            models.CheckConstraint(
                condition=~Q(mode="CHEQUE") | ~Q(cheque_number=""), name="payment_cheque_number"
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "retailer", "payment_date"], name="payment_retailer_idx"
            ),
            models.Index(fields=["tenant", "status", "payment_date"], name="payment_status_idx"),
            models.Index(
                fields=["tenant", "handover_status", "collected_by"], name="payment_handover_idx"
            ),
        ]

    def __str__(self) -> str:
        return self.number


class Refund(TenantScopedModel):
    """Money paid back to a shop from its credit balance (ADR-047 item 4). It debits the ledger and
    uses the shop's unused money oldest first (a target in the allocation engine, covered in
    full when recorded). Own number series (RFD/26-27/000001) and a refund voucher."""

    class Mode(models.TextChoices):
        CASH = "CASH", "Cash"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"
        UPI = "UPI", "UPI"

    number = models.CharField(max_length=16)
    retailer = models.ForeignKey("retailers.Retailer", on_delete=models.PROTECT, related_name="+")
    amount = MoneyField()
    mode = models.CharField(max_length=13, choices=Mode.choices)
    refund_date = models.DateField()  # IST; the ledger entry date
    reference_no = models.CharField(max_length=60, blank=True, default="")
    notes = models.CharField(max_length=500, blank=True, default="")
    recorded_by = models.ForeignKey(
        USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    balance_due = MoneyField(default=0)  # running: not yet covered by credit (0 once recorded)
    voucher_pdf_key = models.CharField(max_length=255, blank=True, default="")
    voucher_pdf_status = models.CharField(max_length=8, default="PENDING")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="uniq_refund_number"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="refund_amount_pos"),
            models.CheckConstraint(
                condition=Q(balance_due__gte=0) & Q(balance_due__lte=F("amount")),
                name="refund_balance",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "retailer", "refund_date"], name="refund_retailer_idx")
        ]

    def __str__(self) -> str:
        return self.number
