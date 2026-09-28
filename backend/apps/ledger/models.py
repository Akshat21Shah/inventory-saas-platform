"""The shop's account (PLAN §2.11, §4.5, spec 5.12, ADR-013/017/046).

- ``LedgerEntry`` is append-only: one entry per money event (invoice, credit note, payment,
  reversal, adjustment), each with the balance after it, written under the account row lock
  (lock order level L1).
- ``Allocation`` matches money to what is owed: a source (payment, credit note, credit
  adjustment) settles a target (invoice, debit adjustment). Also append-only: a reversal is a new
  row with the opposite amount. Allocations never change the balance, only which invoices are
  paid.

Invariant (tested): ``balance = Σ debits - Σ credits = Σ targets' balance due - unapplied credit``.
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from common.fields import MoneyField
from common.models import TenantScopedModel

USER = settings.AUTH_USER_MODEL


class RetailerAccount(TenantScopedModel):
    """One per shop; its row lock serialises every money event and credit check for the shop."""

    retailer = models.OneToOneField(
        "retailers.Retailer", on_delete=models.PROTECT, related_name="account"
    )
    balance = MoneyField(default=0)  # + = the shop owes, - = the shop has credit
    total_debits = MoneyField(default=0)
    total_credits = MoneyField(default=0)
    unapplied_credit = MoneyField(default=0)  # money received or credited, not yet matched
    last_entry_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(balance=F("total_debits") - F("total_credits")),
                name="account_balance_matches_totals",
            ),
            models.CheckConstraint(condition=Q(unapplied_credit__gte=0), name="account_unapplied"),
        ]

    def __str__(self) -> str:
        return f"{self.retailer_id}: {self.balance}"


class EntryType(models.TextChoices):
    OPENING_BALANCE = "OPENING_BALANCE", "Opening balance"
    INVOICE = "INVOICE", "Invoice"
    CREDIT_NOTE = "CREDIT_NOTE", "Credit note"
    PAYMENT = "PAYMENT", "Payment"
    PAYMENT_REVERSAL = "PAYMENT_REVERSAL", "Payment reversed"
    DEBIT_ADJUSTMENT = "DEBIT_ADJUSTMENT", "Debit adjustment"
    CREDIT_ADJUSTMENT = "CREDIT_ADJUSTMENT", "Credit adjustment"


class LedgerEntry(TenantScopedModel):
    """Append-only (database trigger). ``balance_after = previous + debit - credit``."""

    account = models.ForeignKey(RetailerAccount, on_delete=models.PROTECT, related_name="entries")
    retailer = models.ForeignKey("retailers.Retailer", on_delete=models.PROTECT, related_name="+")
    entry_type = models.CharField(max_length=17, choices=EntryType.choices)
    entry_date = models.DateField()  # IST
    debit = MoneyField(default=0)
    credit = MoneyField(default=0)
    balance_after = MoneyField()
    reference_type = models.CharField(max_length=20)  # INVOICE, CREDIT_NOTE, PAYMENT, ADJUSTMENT
    reference_id = models.UUIDField()
    reference_number = models.CharField(max_length=40, blank=True, default="")
    narration = models.CharField(max_length=300, blank=True, default="")
    reverses = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversed_by"
    )
    created_by = models.ForeignKey(
        USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(debit__gte=0)
                & Q(credit__gte=0)
                & (Q(debit__gt=0, credit=0) | Q(credit__gt=0, debit=0)),
                name="ledger_one_side",
            ),
            models.UniqueConstraint(
                fields=["tenant", "reference_type", "reference_id", "entry_type"],
                name="uniq_ledger_posting",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "retailer", "created_at", "id"], name="ledger_retailer_idx"
            ),
            models.Index(fields=["tenant", "entry_date"], name="ledger_date_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.entry_type} {self.debit or -self.credit}"


class LedgerAdjustment(TenantScopedModel):
    """An opening balance or a manual debit/credit (audited). A debit is owed like an invoice (it
    can be paid and ages); a credit is money the shop can use like an advance."""

    class Kind(models.TextChoices):
        OPENING_DEBIT = "OPENING_DEBIT", "Opening balance (owed)"
        OPENING_CREDIT = "OPENING_CREDIT", "Opening balance (advance)"
        DEBIT = "DEBIT", "Debit adjustment"
        CREDIT = "CREDIT", "Credit adjustment"

    retailer = models.ForeignKey("retailers.Retailer", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=14, choices=Kind.choices)
    amount = MoneyField()
    adjustment_date = models.DateField()
    due_date = models.DateField()  # debits age and fall due like invoices
    narration = models.CharField(max_length=300)
    # Running: debits' balance still owed; credits' credit still unused.
    balance_due = MoneyField(default=0)
    unapplied_amount = MoneyField(default=0)
    created_by = models.ForeignKey(
        USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="adjustment_amount_pos"),
            models.CheckConstraint(
                condition=Q(balance_due__gte=0)
                & Q(balance_due__lte=F("amount"))
                & Q(unapplied_amount__gte=0)
                & Q(unapplied_amount__lte=F("amount")),
                name="adjustment_running",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "retailer", "adjustment_date"], name="adjustment_idx")
        ]

    @property
    def is_debit(self) -> bool:
        return self.kind in (self.Kind.OPENING_DEBIT, self.Kind.DEBIT)

    def __str__(self) -> str:
        return f"{self.kind} {self.amount}"


class Allocation(TenantScopedModel):
    """Money matched to what is owed (ADR-017, ADR-046 item 10). Exactly one source and one
    target. Append-only; a reversal has the opposite amount and points at the row it reverses."""

    payment = models.ForeignKey(
        "payments.Payment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="allocations",
    )
    credit_note = models.ForeignKey(
        "billing.CreditNote",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="allocations",
    )
    credit_adjustment = models.ForeignKey(
        LedgerAdjustment, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    invoice = models.ForeignKey(
        "billing.Invoice",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="allocations",
    )
    debit_adjustment = models.ForeignKey(
        LedgerAdjustment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="allocations",
    )
    retailer = models.ForeignKey("retailers.Retailer", on_delete=models.PROTECT, related_name="+")
    amount = MoneyField()  # negative for a reversal
    automatic = models.BooleanField(default=False)  # FIFO or advances applied at issue
    reverses = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversed_by"
    )
    reason = models.CharField(max_length=300, blank=True, default="")
    created_by = models.ForeignKey(
        USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        payment__isnull=False,
                        credit_note__isnull=True,
                        credit_adjustment__isnull=True,
                    )
                    | Q(
                        payment__isnull=True,
                        credit_note__isnull=False,
                        credit_adjustment__isnull=True,
                    )
                    | Q(
                        payment__isnull=True,
                        credit_note__isnull=True,
                        credit_adjustment__isnull=False,
                    )
                ),
                name="allocation_one_source",
            ),
            models.CheckConstraint(
                condition=Q(invoice__isnull=False, debit_adjustment__isnull=True)
                | Q(invoice__isnull=True, debit_adjustment__isnull=False),
                name="allocation_one_target",
            ),
            models.CheckConstraint(
                condition=(Q(amount__gt=0) & Q(reverses__isnull=True))
                | (Q(amount__lt=0) & Q(reverses__isnull=False)),
                name="allocation_sign",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "invoice"], name="allocation_invoice_idx"),
            models.Index(fields=["tenant", "payment"], name="allocation_payment_idx"),
            models.Index(
                fields=["tenant", "retailer", "created_at"], name="allocation_retailer_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"allocation {self.amount}"
