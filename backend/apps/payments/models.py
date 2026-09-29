"""Payments (PLAN §2.12, §4.6, spec 5.12, ADR-017/046). Offline payments in Phase 5; online
gateway payments (Phase 7) add columns, not a new shape. Status changes and every ledger effect go
through the services."""

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from common.crypto import EncryptedTextField
from common.fields import MoneyField
from common.models import TenantScopedModel

USER = settings.AUTH_USER_MODEL


class Payment(TenantScopedModel):
    class Mode(models.TextChoices):
        CASH = "CASH", "Cash"
        CHEQUE = "CHEQUE", "Cheque"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"
        UPI = "UPI", "UPI"
        ONLINE = "ONLINE", "Paid online"  # through the payment gateway only (Phase 7)

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
    # Paid online (Phase 7): the gateway's payment, its checkout, and a flag for staff when the
    # amount differed from the checkout's (ADR-049 item 9, plan answer 10).
    gateway_provider = models.CharField(max_length=10, blank=True, default="")
    gateway_payment_id = models.CharField(max_length=60, blank=True, default="")
    intent = models.ForeignKey(
        "payments.PaymentIntent",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payments",
    )
    needs_review = models.BooleanField(default=False)
    review_reason = models.CharField(max_length=300, blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

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
            models.UniqueConstraint(  # a gateway payment is recorded once, whoever reports it
                fields=["tenant", "gateway_provider", "gateway_payment_id"],
                condition=~Q(gateway_payment_id=""),
                name="uniq_gateway_payment",
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

    class Status(models.TextChoices):
        ISSUED = "ISSUED", "Paid back"
        REVERSED = "REVERSED", "Reversed"  # entered in error: the shop's credit is restored

    number = models.CharField(max_length=16)
    retailer = models.ForeignKey("retailers.Retailer", on_delete=models.PROTECT, related_name="+")
    amount = MoneyField()
    mode = models.CharField(max_length=13, choices=Mode.choices)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.ISSUED)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(
        USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reversal_reason = models.CharField(max_length=300, blank=True, default="")
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


# What staff and salesmen record by hand; ONLINE comes only from the gateway (Phase 7).
MANUAL_MODES = [choice for choice in Payment.Mode.choices if choice[0] != Payment.Mode.ONLINE]


class GatewayConfig(TenantScopedModel):
    """A distributor's own payment gateway account (ADR-049 item 9): money settles to the
    distributor, never to the platform. Keys and the webhook secret are encrypted and never
    returned. The super admin switches the module on; the owner enters and checks the keys."""

    class Provider(models.TextChoices):
        RAZORPAY = "RAZORPAY", "Razorpay"
        MOCK = "MOCK", "Test gateway (development)"

    class Mode(models.TextChoices):
        TEST = "TEST", "Test"
        LIVE = "LIVE", "Live"

    class Status(models.TextChoices):
        UNVERIFIED = "UNVERIFIED", "Not checked"
        CHECKING = "CHECKING", "Checking"
        VERIFIED = "VERIFIED", "Working"
        FAILED = "FAILED", "Not working"

    provider = models.CharField(max_length=10, choices=Provider.choices)
    mode = models.CharField(max_length=4, choices=Mode.choices, default=Mode.TEST)
    key_id = EncryptedTextField(default="")
    key_secret = EncryptedTextField(default="")
    webhook_secret = EncryptedTextField(default="")
    is_active = models.BooleanField(default=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNVERIFIED)
    verified_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True, default="")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant"], name="uniq_gateway_config"),
        ]

    def __str__(self) -> str:
        return f"{self.provider} ({self.mode})"


class PaymentIntent(TenantScopedModel):
    """A shop's online checkout (ADR-049 items 9 and 10): what it pays (a bill's balance,
    everything it owes, or an amount it chose), the gateway order for it, and how it ended. At
    most one active checkout per shop and target at a time: a second tap reuses it."""

    class Purpose(models.TextChoices):
        INVOICE = "INVOICE", "A bill"
        OUTSTANDING = "OUTSTANDING", "Everything owed"
        CUSTOM = "CUSTOM", "An amount of the shop's choice"

    class Status(models.TextChoices):
        CREATED = "CREATED", "Ready to pay"
        ATTEMPTED = "ATTEMPTED", "Tried"  # the shop opened or tried the checkout
        PAID = "PAID", "Paid"
        EXPIRED = "EXPIRED", "Expired"

    ACTIVE = ("CREATED", "ATTEMPTED")

    retailer = models.ForeignKey("retailers.Retailer", on_delete=models.PROTECT, related_name="+")
    purpose = models.CharField(max_length=11, choices=Purpose.choices)
    invoice = models.ForeignKey(
        "billing.Invoice", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    amount = MoneyField()
    provider = models.CharField(max_length=10)
    provider_order_id = models.CharField(max_length=60, blank=True, default="")
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.CREATED)
    checkout = models.JSONField(default=dict)  # what the shop's page opens (no secrets)
    payment = models.ForeignKey(
        Payment, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    expires_at = models.DateTimeField()
    client_outcome = models.CharField(max_length=10, blank=True, default="")  # informational
    last_error = models.CharField(max_length=300, blank=True, default="")
    paid_at = models.DateTimeField(null=True, blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "retailer", "purpose", "invoice"],
                condition=Q(status__in=["CREATED", "ATTEMPTED"]),
                nulls_distinct=False,
                name="uniq_active_checkout",
            ),
            models.UniqueConstraint(
                fields=["provider", "provider_order_id"],
                condition=~Q(provider_order_id=""),
                name="uniq_gateway_order",
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="intent_amount_pos"),
            models.CheckConstraint(
                condition=Q(purpose="INVOICE", invoice__isnull=False)
                | (~Q(purpose="INVOICE") & Q(invoice__isnull=True)),
                name="intent_invoice_for_bills",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "created_at"], name="intent_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.purpose} {self.amount} {self.status}"


class WebhookEvent(TenantScopedModel):
    """Every gateway event whose signature checked out, once (by the gateway's event id)."""

    provider = models.CharField(max_length=10)
    event_id = models.CharField(max_length=80)
    kind = models.CharField(max_length=20)
    payload = models.JSONField(default=dict)
    result = models.CharField(max_length=40, blank=True, default="")
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "provider", "event_id"], name="uniq_webhook_event"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provider} {self.event_id}"
