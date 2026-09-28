"""Billing documents (PLAN §2.9, spec 5.10, ADR-007/009/010/011/046): number series, tax invoices,
credit notes and Order Confirmations. Issued documents never change except their payment, PDF and
e-invoice columns (a database trigger enforces it); corrections are credit notes. All write logic
lives in the services; amounts come from ``billing/tax.py``."""

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from common.fields import MoneyField, QtyField, RateField
from common.models import TenantScopedModel

USER = settings.AUTH_USER_MODEL


class DocumentType(models.TextChoices):
    INVOICE = "INVOICE", "Tax invoice"
    CREDIT_NOTE = "CREDIT_NOTE", "Credit note"
    RECEIPT = "RECEIPT", "Payment receipt"


class DocumentSeries(TenantScopedModel):
    """Gapless numbers per document type and financial year: ``INV/26-27/000001`` (ADR-046).
    ``next_number`` is taken under a row lock inside the issuing transaction."""

    document_type = models.CharField(max_length=12, choices=DocumentType.choices)
    fy = models.CharField(max_length=7)  # "2026-27"
    prefix = models.CharField(max_length=3)  # A-Z 0-9; with "/26-27/" and 6 digits ≤ 16 chars
    padding = models.PositiveSmallIntegerField(default=6)
    next_number = models.BigIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "document_type", "fy"], name="uniq_series_per_fy"
            ),
            models.CheckConstraint(
                condition=Q(prefix__regex=r"^[A-Z0-9]{1,3}$"), name="series_prefix"
            ),
            models.CheckConstraint(condition=Q(next_number__gte=1), name="series_next_pos"),
            models.CheckConstraint(
                condition=Q(padding__gte=4, padding__lte=6), name="series_padding"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.document_type} {self.fy} ({self.prefix})"


class PdfStatus(models.TextChoices):
    PENDING = "PENDING", "Being prepared"
    READY = "READY", "Ready"
    FAILED = "FAILED", "Failed"


class EInvoiceStatus(models.TextChoices):
    """Phase 7 fills these in; until then every document is NOT_APPLICABLE (ADR-046 item 11)."""

    NOT_APPLICABLE = "NOT_APPLICABLE", "Not applicable"
    PENDING = "PENDING", "Pending"
    GENERATED = "GENERATED", "Generated"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"


class PaymentStatus(models.TextChoices):
    UNPAID = "UNPAID", "Unpaid"
    PARTIAL = "PARTIAL", "Partly paid"
    PAID = "PAID", "Paid"


class DocumentStatus(models.TextChoices):
    ISSUED = "ISSUED", "Issued"
    CANCELLED = "CANCELLED", "Cancelled"  # only by IRN cancellation (Phase 7)


class _TaxDocument(TenantScopedModel):
    """What invoices and credit notes share: the party snapshots, supply type, totals, PDF and
    e-invoice columns."""

    number = models.CharField(max_length=16)
    series = models.ForeignKey(DocumentSeries, on_delete=models.PROTECT, related_name="+")
    fy = models.CharField(max_length=7)
    status = models.CharField(
        max_length=10, choices=DocumentStatus.choices, default=DocumentStatus.ISSUED
    )
    retailer = models.ForeignKey("retailers.Retailer", on_delete=models.PROTECT, related_name="+")
    seller = models.JSONField(default=dict)  # legal/trade name, GSTIN, address, state (snapshot)
    buyer = models.JSONField(default=dict)  # name, GSTIN, billing and shipping address, state
    place_of_supply = models.ForeignKey(
        "platform.State", on_delete=models.PROTECT, related_name="+"
    )
    supply_type = models.CharField(max_length=5)  # INTRA / INTER
    reverse_charge = models.BooleanField(default=False)
    prices_include_tax = models.BooleanField(default=False)  # from the order's snapshot
    settings_snapshot = models.JSONField(default=dict)  # rounding keys in effect at issue
    gross_total = MoneyField(default=0)
    discount_total = MoneyField(default=0)
    taxable_total = MoneyField(default=0)
    cgst_total = MoneyField(default=0)
    sgst_total = MoneyField(default=0)
    igst_total = MoneyField(default=0)
    cess_total = MoneyField(default=0)
    round_off = MoneyField(default=0)
    grand_total = MoneyField(default=0)
    amount_in_words = models.CharField(max_length=300, blank=True, default="")
    issued_by = models.ForeignKey(
        USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # PDF (rendered in the background, ADR-046 item 12)
    pdf_key = models.CharField(max_length=255, blank=True, default="")
    pdf_status = models.CharField(
        max_length=8, choices=PdfStatus.choices, default=PdfStatus.PENDING
    )
    # E-invoice (Phase 7)
    einvoice_status = models.CharField(
        max_length=15, choices=EInvoiceStatus.choices, default=EInvoiceStatus.NOT_APPLICABLE
    )
    irn = models.CharField(max_length=64, blank=True, default="")
    ack_no = models.CharField(max_length=20, blank=True, default="")
    ack_date = models.DateTimeField(null=True, blank=True)
    signed_qr = models.TextField(blank=True, default="")

    class Meta:
        abstract = True


class Invoice(_TaxDocument):
    """One per shipment (ADR-006/007). ``balance_due`` = grand total - paid - credited, kept by the
    payment and credit-note services under the invoice row lock."""

    class Trigger(models.TextChoices):
        ON_DISPATCH = "ON_DISPATCH", "At dispatch"
        ON_ACCEPTANCE = "ON_ACCEPTANCE", "At acceptance"
        ON_ALLOCATION = "ON_ALLOCATION", "At backorder allocation"
        AFTER_DISPATCH = "AFTER_DISPATCH", "After dispatch (Phase 4 data)"  # ADR-046 item 3

    invoice_date = models.DateField()  # IST
    due_date = models.DateField()
    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="invoices")
    fulfilment = models.OneToOneField(
        "orders.Fulfilment", on_delete=models.PROTECT, related_name="invoice"
    )
    issued_trigger = models.CharField(max_length=14, choices=Trigger.choices)
    rate_differs_from_order = models.BooleanField(default=False)
    # Running columns (the only ones that change after issue, with PDF and e-invoice columns)
    amount_paid = MoneyField(default=0)
    amount_credited = MoneyField(default=0)
    balance_due = MoneyField(default=0)
    payment_status = models.CharField(
        max_length=8, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )
    copies_pdf_key = models.CharField(max_length=255, blank=True, default="")  # staff: 3 copies

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="uniq_invoice_number"),
            models.CheckConstraint(condition=Q(grand_total__gte=0), name="invoice_total_nonneg"),
            models.CheckConstraint(
                condition=Q(round_off__gt=-1) & Q(round_off__lt=1), name="invoice_round_off"
            ),
            models.CheckConstraint(
                condition=Q(amount_paid__gte=0)
                & Q(amount_credited__gte=0)
                & Q(balance_due__gte=0)
                & Q(balance_due=F("grand_total") - F("amount_paid") - F("amount_credited")),
                name="invoice_balance",
            ),
        ]
        indexes = [
            models.Index("tenant", F("invoice_date").desc(), name="invoice_date_idx"),
            models.Index(
                fields=["tenant", "retailer", "invoice_date"], name="invoice_retailer_idx"
            ),
            models.Index(
                fields=["tenant", "payment_status", "due_date"], name="invoice_payment_idx"
            ),
            models.Index(fields=["tenant", "einvoice_status"], name="invoice_einvoice_idx"),
        ]

    def __str__(self) -> str:
        return self.number


class InvoiceLine(TenantScopedModel):
    """Append-only. Amounts are exclusive of GST (``gross_amount - discount_amount =
    taxable_value``); ``unit_price`` is as ordered (inclusive when the order's prices were)."""

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    order_line = models.ForeignKey("orders.OrderLine", on_delete=models.PROTECT, related_name="+")
    fulfilment_line = models.ForeignKey(
        "orders.FulfilmentLine", on_delete=models.PROTECT, related_name="+"
    )
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    description = models.CharField(max_length=300)
    product_code = models.CharField(max_length=40)
    hsn_code = models.CharField(max_length=8)
    unit_code = models.CharField(max_length=10)
    quantity = QtyField()
    unit_price = MoneyField()
    gross_amount = MoneyField()
    discount_amount = MoneyField(default=0)
    taxable_value = MoneyField()
    gst_rate = RateField()
    cgst_rate = RateField(default=0)
    cgst_amount = MoneyField(default=0)
    sgst_rate = RateField(default=0)
    sgst_amount = MoneyField(default=0)
    igst_rate = RateField(default=0)
    igst_amount = MoneyField(default=0)
    cess_rate = RateField(default=0)
    cess_amount = MoneyField(default=0)
    line_total = MoneyField()
    order_rate = RateField()  # the GST rate when the order was placed
    rate_differs_from_order = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["invoice", "line_no"], name="uniq_invoice_line_no"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="invoice_line_qty_pos"),
            models.CheckConstraint(
                condition=Q(taxable_value__gte=0)
                & Q(cgst_amount__gte=0)
                & Q(sgst_amount__gte=0)
                & Q(igst_amount__gte=0)
                & Q(cess_amount__gte=0),
                name="invoice_line_amounts_nonneg",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.invoice_id}#{self.line_no}"


class CreditNote(_TaxDocument):
    """Corrects one invoice (spec 5.10, ADR-046 items 4-5). ``applied_to_invoice`` reduced the
    invoice's balance; the rest (``grand_total - applied_to_invoice``) became credit for the shop,
    of which ``unapplied_amount`` is not yet used."""

    class Kind(models.TextChoices):
        RETURN = "RETURN", "Return"
        SHORT_SUPPLY = "SHORT_SUPPLY", "Short supply"
        CANCELLATION = "CANCELLATION", "Cancellation"
        PRICE_ADJUSTMENT = "PRICE_ADJUSTMENT", "Price adjustment"

    class ReturnReason(models.TextChoices):
        DAMAGED = "DAMAGED", "Damaged"
        EXPIRED = "EXPIRED", "Expired"
        WRONG_ITEM = "WRONG_ITEM", "Wrong item"
        EXCESS_SUPPLY = "EXCESS_SUPPLY", "Excess supply"
        OTHER = "OTHER", "Other"

    note_date = models.DateField()  # IST
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="credit_notes")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    return_reason = models.CharField(
        max_length=13, choices=ReturnReason.choices, blank=True, default=""
    )
    reason_note = models.CharField(max_length=500, blank=True, default="")
    issued_automatically = models.BooleanField(default=False)
    applied_to_invoice = MoneyField(default=0)  # applied to its own invoice when issued
    unapplied_amount = MoneyField(default=0)  # running: credit not yet used

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="uniq_credit_note_number"),
            models.CheckConstraint(
                condition=Q(grand_total__gte=0), name="credit_note_total_nonneg"
            ),
            models.CheckConstraint(
                condition=Q(applied_to_invoice__gte=0)
                & Q(applied_to_invoice__lte=F("grand_total"))
                & Q(unapplied_amount__gte=0)
                & Q(unapplied_amount__lte=F("grand_total")),
                name="credit_note_application",
            ),
            models.CheckConstraint(
                condition=~Q(kind="RETURN") | ~Q(return_reason=""), name="credit_note_return_reason"
            ),
        ]
        indexes = [
            models.Index("tenant", F("note_date").desc(), name="credit_note_date_idx"),
            models.Index(fields=["tenant", "invoice"], name="credit_note_invoice_idx"),
        ]

    def __str__(self) -> str:
        return self.number


class CreditNoteLine(TenantScopedModel):
    """Append-only. ``quantity`` 0 for value-only credits."""

    class Disposition(models.TextChoices):
        RETURN_TO_STOCK = "RETURN_TO_STOCK", "Return to stock"
        DAMAGED = "DAMAGED", "Received damaged"
        NOT_RETURNED = "NOT_RETURNED", "Not physically returned"

    credit_note = models.ForeignKey(CreditNote, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    invoice_line = models.ForeignKey(InvoiceLine, on_delete=models.PROTECT, related_name="credits")
    quantity = QtyField(default=0)
    disposition = models.CharField(
        max_length=15, choices=Disposition.choices, blank=True, default=""
    )
    taxable_value = MoneyField()
    cgst_amount = MoneyField(default=0)
    sgst_amount = MoneyField(default=0)
    igst_amount = MoneyField(default=0)
    cess_amount = MoneyField(default=0)
    line_total = MoneyField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["credit_note", "line_no"], name="uniq_credit_note_line_no"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=0)
                & Q(taxable_value__gte=0)
                & Q(cgst_amount__gte=0)
                & Q(sgst_amount__gte=0)
                & Q(igst_amount__gte=0)
                & Q(cess_amount__gte=0),
                name="credit_note_line_nonneg",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.credit_note_id}#{self.line_no}"


class OrderConfirmation(TenantScopedModel):
    """The document sent at acceptance (ADR-007, ADR-046 item 2): items, prices and a tax estimate,
    "This is not a tax invoice." ``content`` is a snapshot, so later changes don't alter it."""

    order = models.OneToOneField(
        "orders.Order", on_delete=models.PROTECT, related_name="confirmation"
    )
    content = models.JSONField(default=dict)
    pdf_key = models.CharField(max_length=255, blank=True, default="")
    pdf_status = models.CharField(
        max_length=8, choices=PdfStatus.choices, default=PdfStatus.PENDING
    )

    def __str__(self) -> str:
        return f"confirmation {self.order_id}"
