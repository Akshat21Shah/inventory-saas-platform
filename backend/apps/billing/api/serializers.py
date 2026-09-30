"""Invoice and credit-note representation (PLAN §3.10). Validation only; every figure comes from
the saved documents (the thin-client rule)."""

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.billing.models import (
    CreditNote,
    CreditNoteLine,
    DocumentStatus,
    DocumentType,
    EInvoiceStatus,
    Invoice,
    PaymentStatus,
    PdfStatus,
)
from apps.compliance.api.serializers import EInvoiceSummarySerializer, EWayBillSummarySerializer
from apps.pricing.api.serializers import ShopRefSerializer, money, qty
from common.dates import today_ist


def rate(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=6, decimal_places=3, **kwargs)


class OrderRefSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    number = serializers.CharField()


class DocumentRefSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    number = serializers.CharField()


class DocumentLinkSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=PdfStatus.choices)
    url = serializers.URLField(allow_null=True, help_text="Valid for 5 minutes; null until READY.")


class InvoiceRowSerializer(serializers.ModelSerializer[Invoice]):
    retailer = ShopRefSerializer()
    order = OrderRefSerializer()
    payment_status = serializers.ChoiceField(choices=PaymentStatus.choices)
    pdf_status = serializers.ChoiceField(choices=PdfStatus.choices)
    einvoice_status = serializers.ChoiceField(choices=EInvoiceStatus.choices)
    issued_trigger = serializers.ChoiceField(choices=Invoice.Trigger.choices)
    grand_total = money()
    balance_due = money()
    days_overdue = serializers.SerializerMethodField()
    status = serializers.ChoiceField(
        choices=DocumentStatus.choices,
        help_text="CANCELLED only when its IRN was cancelled (Phase 7); it then owes nothing.",
    )

    class Meta:
        model = Invoice
        fields = [
            "id",
            "number",
            "invoice_date",
            "due_date",
            "retailer",
            "order",
            "grand_total",
            "balance_due",
            "payment_status",
            "days_overdue",
            "issued_trigger",
            "rate_differs_from_order",
            "pdf_status",
            "einvoice_status",
            "status",
        ]

    def get_days_overdue(self, invoice: Invoice) -> int:
        """Days past the due date while something is owed; 0 otherwise."""
        if invoice.balance_due <= 0:
            return 0
        return max((today_ist() - invoice.due_date).days, 0)


class InvoiceLineSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    line_no = serializers.IntegerField()
    product_id = serializers.UUIDField()
    product_code = serializers.CharField()
    description = serializers.CharField()
    hsn_code = serializers.CharField()
    unit_code = serializers.CharField()
    quantity = qty()
    unit_price = money()
    gross_amount = money()
    discount_amount = money()
    taxable_value = money()
    gst_rate = rate()
    cgst_rate = rate()
    cgst_amount = money()
    sgst_rate = rate()
    sgst_amount = money()
    igst_rate = rate()
    igst_amount = money()
    cess_rate = rate()
    cess_amount = money()
    line_total = money()
    order_rate = rate()
    rate_differs_from_order = serializers.BooleanField()
    credited_quantity = qty(help_text="Already credited by credit notes.")


class AppliedSerializer(serializers.Serializer[Any]):
    """Money matched to this document: a payment, credit-note credit or a credit adjustment."""

    id = serializers.UUIDField()
    source_type = serializers.ChoiceField(choices=["PAYMENT", "CREDIT_NOTE", "ADJUSTMENT"])
    source_id = serializers.UUIDField()
    source_number = serializers.CharField()
    amount = money(help_text="Negative when it undoes an earlier allocation.")
    automatic = serializers.BooleanField()
    reversed = serializers.BooleanField()
    created_at = serializers.DateTimeField()


class UsedForSerializer(serializers.Serializer[Any]):
    """Where money went: an invoice, a debit adjustment (old bill, debit) or a refund."""

    id = serializers.UUIDField()
    target_type = serializers.ChoiceField(choices=["INVOICE", "ADJUSTMENT", "REFUND"])
    target_id = serializers.UUIDField()
    target_number = serializers.CharField()
    amount = money(help_text="Negative when it undoes an earlier allocation.")
    automatic = serializers.BooleanField()
    reversed = serializers.BooleanField()
    created_at = serializers.DateTimeField()


class CreditNoteRowSerializer(serializers.ModelSerializer[CreditNote]):
    retailer = ShopRefSerializer()
    invoice = DocumentRefSerializer()
    kind = serializers.ChoiceField(choices=CreditNote.Kind.choices)
    return_reason = serializers.ChoiceField(
        choices=CreditNote.ReturnReason.choices, allow_blank=True
    )
    pdf_status = serializers.ChoiceField(choices=PdfStatus.choices)
    grand_total = money()
    applied_to_invoice = money()
    unapplied_amount = money(help_text="Credit not yet used for other dues.")

    class Meta:
        model = CreditNote
        fields = [
            "id",
            "number",
            "note_date",
            "kind",
            "return_reason",
            "issued_automatically",
            "retailer",
            "invoice",
            "grand_total",
            "applied_to_invoice",
            "unapplied_amount",
            "pdf_status",
        ]


class TotalsSerializer(serializers.Serializer[Any]):
    gross_total = money()
    discount_total = money()
    taxable_total = money()
    cgst_total = money()
    sgst_total = money()
    igst_total = money()
    cess_total = money()
    round_off = money()
    grand_total = money()


class PlaceSerializer(serializers.Serializer[Any]):
    code = serializers.CharField(source="pk")
    name = serializers.CharField()


class InvoiceDetailSerializer(InvoiceRowSerializer):
    seller = serializers.JSONField()
    buyer = serializers.JSONField()
    place_of_supply = PlaceSerializer()
    supply_type = serializers.ChoiceField(choices=["INTRA", "INTER"])
    totals = TotalsSerializer(source="*")
    amount_in_words = serializers.CharField()
    amount_paid = money()
    amount_credited = money()
    fulfilment_id = serializers.UUIDField()
    lines = InvoiceLineSerializer(many=True)
    credit_notes = CreditNoteRowSerializer(many=True)
    applied = AppliedSerializer(many=True, source="applied_rows")
    irn = serializers.CharField()
    ack_no = serializers.CharField()
    ack_date = serializers.DateTimeField(allow_null=True)
    einvoice = serializers.SerializerMethodField()
    ewaybill = serializers.SerializerMethodField()

    @extend_schema_field(EInvoiceSummarySerializer(allow_null=True))
    def get_einvoice(self, obj: Invoice) -> dict[str, Any] | None:
        return _einvoice(obj)

    @extend_schema_field(EWayBillSummarySerializer(allow_null=True))
    def get_ewaybill(self, obj: Invoice) -> dict[str, Any] | None:
        from apps.compliance.selectors import ewaybill_for

        found = ewaybill_for(obj)
        return dict(EWayBillSummarySerializer(found).data) if found is not None else None

    class Meta(InvoiceRowSerializer.Meta):
        fields = [
            *InvoiceRowSerializer.Meta.fields,
            "seller",
            "buyer",
            "place_of_supply",
            "supply_type",
            "prices_include_tax",
            "reverse_charge",
            "totals",
            "amount_in_words",
            "amount_paid",
            "amount_credited",
            "settings_snapshot",
            "fulfilment_id",
            "lines",
            "credit_notes",
            "applied",
            "irn",
            "ack_no",
            "ack_date",
            "einvoice",
            "ewaybill",
        ]


class ShopInvoiceDetailSerializer(InvoiceDetailSerializer):
    """The shop's view: the same bill without the office's e-invoice workings (the IRN itself is
    on the bill and its PDF)."""

    class Meta(InvoiceDetailSerializer.Meta):
        fields = [
            f for f in InvoiceDetailSerializer.Meta.fields if f not in ("einvoice", "ewaybill")
        ]


def _einvoice(doc: Invoice | CreditNote) -> dict[str, Any] | None:
    """The document's IRN record, when it has one (Phase 7; null while e-invoicing is off)."""
    from apps.compliance.selectors import summary_for

    found = summary_for(doc)
    return dict(EInvoiceSummarySerializer(found).data) if found is not None else None


class CreditNoteLineSerializer(serializers.Serializer[Any]):
    line_no = serializers.IntegerField()
    invoice_line_id = serializers.UUIDField()
    description = serializers.CharField(source="invoice_line.description")
    product_code = serializers.CharField(source="invoice_line.product_code")
    hsn_code = serializers.CharField(source="invoice_line.hsn_code")
    unit_code = serializers.CharField(source="invoice_line.unit_code")
    gst_rate = rate(source="invoice_line.gst_rate")
    quantity = qty()
    disposition = serializers.ChoiceField(
        choices=CreditNoteLine.Disposition.choices, allow_blank=True
    )
    taxable_value = money()
    cgst_amount = money()
    sgst_amount = money()
    igst_amount = money()
    cess_amount = money()
    line_total = money()


class CreditNoteDetailSerializer(CreditNoteRowSerializer):
    seller = serializers.JSONField()
    buyer = serializers.JSONField()
    place_of_supply = PlaceSerializer()
    supply_type = serializers.ChoiceField(choices=["INTRA", "INTER"])
    reason_note = serializers.CharField()
    totals = TotalsSerializer(source="*")
    amount_in_words = serializers.CharField()
    lines = CreditNoteLineSerializer(many=True)
    used_for = UsedForSerializer(many=True, source="used_for_rows")
    irn = serializers.CharField()
    ack_no = serializers.CharField()
    ack_date = serializers.DateTimeField(allow_null=True)
    einvoice = serializers.SerializerMethodField()

    @extend_schema_field(EInvoiceSummarySerializer(allow_null=True))
    def get_einvoice(self, obj: CreditNote) -> dict[str, Any] | None:
        return _einvoice(obj)

    class Meta(CreditNoteRowSerializer.Meta):
        fields = [
            *CreditNoteRowSerializer.Meta.fields,
            "seller",
            "buyer",
            "place_of_supply",
            "supply_type",
            "reason_note",
            "totals",
            "amount_in_words",
            "lines",
            "used_for",
            "irn",
            "ack_no",
            "ack_date",
            "einvoice",
        ]


# --- Requests ---------------------------------------------------------------------------------


class CreditNoteLineInputSerializer(serializers.Serializer[Any]):
    invoice_line = serializers.UUIDField()
    quantity = qty(required=False, min_value=0, help_text="Returns: how many came back.")
    disposition = serializers.ChoiceField(
        choices=CreditNoteLine.Disposition.choices,
        required=False,
        default=CreditNoteLine.Disposition.RETURN_TO_STOCK,
    )
    taxable_value = money(
        required=False, min_value=0, help_text="Price adjustments: the taxable value to credit."
    )


class CreditNoteCreateSerializer(serializers.Serializer[Any]):
    invoice = serializers.UUIDField()
    kind = serializers.ChoiceField(
        choices=[CreditNote.Kind.RETURN, CreditNote.Kind.PRICE_ADJUSTMENT]
    )
    reason = serializers.ChoiceField(
        choices=CreditNote.ReturnReason.choices,
        required=False,
        allow_blank=True,
        default="",
        help_text="Required for returns.",
    )
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    lines = CreditNoteLineInputSerializer(many=True)


class DocumentSeriesSerializer(serializers.Serializer[Any]):
    document_type = serializers.ChoiceField(choices=DocumentType.choices)
    prefix = serializers.CharField()
    fy = serializers.CharField(help_text="Financial year, e.g. 2026-27.")
    next_number = serializers.CharField(help_text="The number the next document will get.")
    issued = serializers.IntegerField(help_text="Documents numbered this financial year.")


class DocumentSeriesChangeSerializer(serializers.Serializer[Any]):
    document_type = serializers.ChoiceField(choices=DocumentType.choices)
    prefix = serializers.CharField(max_length=3, help_text="1 to 3 capital letters or digits.")
