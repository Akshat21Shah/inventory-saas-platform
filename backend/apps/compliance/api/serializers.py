from typing import Any

from rest_framework import serializers

from apps.compliance.ewaybill_reasons import CANCEL_REASONS, PART_B_REASONS
from apps.compliance.models import (
    CancelReason,
    DocumentType,
    EInvoiceRecord,
    EWayBill,
    EWayBillUpdate,
    GstCredential,
)
from apps.compliance.rules import BANDS


class GstCredentialsSerializer(serializers.Serializer[Any]):
    provider = serializers.CharField()
    field_names = serializers.ListField(
        child=serializers.CharField(), help_text="The provider's credential fields, in order."
    )
    required_fields = serializers.ListField(child=serializers.CharField())
    environment = serializers.ChoiceField(choices=GstCredential.Environment.choices)
    gstin = serializers.CharField()
    saved = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        help_text="Each field's last characters (empty when not saved); never the value.",
    )
    status = serializers.ChoiceField(choices=GstCredential.Status.choices)
    verified_at = serializers.DateTimeField(allow_null=True)
    last_error = serializers.CharField(allow_blank=True)


class GstCredentialsInputSerializer(serializers.Serializer[Any]):
    environment = serializers.ChoiceField(choices=GstCredential.Environment.choices)
    values = serializers.DictField(
        child=serializers.CharField(max_length=500, allow_blank=True, trim_whitespace=True),
        help_text="The provider's fields; a blank one keeps the saved value.",
    )


class TurnoverSerializer(serializers.Serializer[Any]):
    turnover_band = serializers.ChoiceField(choices=[(b, b) for b in BANDS])
    einvoice_suggested = serializers.BooleanField()
    reporting_limit_applies = serializers.BooleanField()
    reporting_days = serializers.IntegerField()
    einvoice_enabled = serializers.BooleanField()
    ewaybill_enabled = serializers.BooleanField()


class TurnoverInputSerializer(serializers.Serializer[Any]):
    turnover_band = serializers.ChoiceField(choices=[(b, b) for b in BANDS])


class DocumentNumberSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    number = serializers.CharField()


class CancelBlockSerializer(serializers.Serializer[Any]):
    reason = serializers.ChoiceField(choices=["WINDOW_OVER", "EWAY_BILL", "CREDIT_NOTES"])
    message = serializers.CharField(help_text="What to do first, in plain words.")
    ewaybill_id = serializers.UUIDField(required=False, allow_null=True)


class EInvoiceSummarySerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=EInvoiceRecord.Status.choices)
    irn = serializers.CharField(allow_blank=True)
    ack_no = serializers.CharField(allow_blank=True)
    ack_date = serializers.DateTimeField(allow_null=True)
    error_code = serializers.CharField(allow_blank=True)
    error_message = serializers.CharField(allow_blank=True)
    retryable = serializers.BooleanField()
    attempts = serializers.IntegerField()
    requested_at = serializers.DateTimeField(allow_null=True)
    next_retry_at = serializers.DateTimeField(allow_null=True)
    generated_at = serializers.DateTimeField(allow_null=True)
    report_by = serializers.DateField(
        allow_null=True, help_text="The last day for the IRN, when the reporting limit applies."
    )
    past_report_by = serializers.BooleanField()
    can_request = serializers.BooleanField(help_text='"Get IRN" or "Try again" is offered.')
    can_cancel = serializers.BooleanField(
        help_text="An invoice's IRN, within the window, with nothing in the way."
    )
    cancel_blocked = CancelBlockSerializer(
        allow_null=True, help_text="Why the IRN can't be cancelled, and what to do first."
    )
    cancel_until = serializers.DateTimeField(allow_null=True)
    cancel_reason_code = serializers.CharField(allow_blank=True)
    cancel_remarks = serializers.CharField(allow_blank=True)
    cancel_outcome = serializers.ChoiceField(
        choices=EInvoiceRecord.CancelOutcome.choices, allow_blank=True
    )
    cancel_error = serializers.CharField(
        allow_blank=True, help_text="Why the last cancellation was refused."
    )
    cancelled_at = serializers.DateTimeField(allow_null=True)
    reissued_invoice = DocumentNumberSerializer(allow_null=True)


class EInvoiceRowSerializer(EInvoiceSummarySerializer):
    document_type = serializers.ChoiceField(choices=DocumentType.choices)
    document_id = serializers.UUIDField()
    document_number = serializers.CharField()
    document_date = serializers.DateField()
    shop_name = serializers.CharField()
    retailer_id = serializers.UUIDField()
    grand_total = serializers.DecimalField(max_digits=14, decimal_places=2)
    invoice_id = serializers.UUIDField(
        help_text="The invoice, or the one the credit note corrects."
    )


class EInvoiceCancelSerializer(serializers.Serializer[Any]):
    reason_code = serializers.ChoiceField(choices=CancelReason.choices)
    remarks = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    outcome = serializers.ChoiceField(
        choices=EInvoiceRecord.CancelOutcome.choices,
        default=EInvoiceRecord.CancelOutcome.REISSUE,
        help_text="REISSUE (default): a corrected invoice with a new number for the same "
        "shipment. TAKE_BACK: the goods come back to stock.",
    )
    to_backorder = serializers.BooleanField(
        default=False, help_text="TAKE_BACK: the quantities wait on backorder (else cancelled)."
    )
    confirm_rate_changes = serializers.BooleanField(
        default=False,
        help_text="REISSUE when a line's GST rate valid today differs: the re-issued invoice "
        "keeps the original rates (see reissue-preview).",
    )


class ReissueRateChangeSerializer(serializers.Serializer[Any]):
    line_no = serializers.IntegerField()
    description = serializers.CharField()
    hsn_code = serializers.CharField()
    original_rate = serializers.DecimalField(max_digits=6, decimal_places=3)
    today_rate = serializers.DecimalField(max_digits=6, decimal_places=3)


class ReissueBuyerSerializer(serializers.Serializer[Any]):
    name = serializers.CharField()
    gstin = serializers.CharField(allow_blank=True)
    state_code = serializers.CharField()


class ReissuePreviewSerializer(serializers.Serializer[Any]):
    buyer = ReissueBuyerSerializer(help_text="The shop's details now: the re-issue uses them.")
    buyer_changed = serializers.BooleanField()
    supply_type = serializers.ChoiceField(choices=["INTRA", "INTER"])
    supply_type_before = serializers.ChoiceField(choices=["INTRA", "INTER"])
    rate_changes = ReissueRateChangeSerializer(
        many=True, help_text="Lines whose GST rate valid today differs from the original."
    )


class EInvoiceCountsSerializer(serializers.Serializer[Any]):
    pending = serializers.IntegerField()
    failed = serializers.IntegerField()
    near_report_by = serializers.IntegerField(
        help_text="Still without an IRN, 3 days or less from the reporting limit."
    )


# --- E-way bills --------------------------------------------------------------------------------


class EWayBillSummarySerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=EWayBill.Status.choices)
    ewb_number = serializers.CharField(allow_blank=True)
    ewb_date = serializers.DateTimeField(allow_null=True)
    valid_until = serializers.DateTimeField(allow_null=True)
    consignment_value = serializers.DecimalField(max_digits=14, decimal_places=2)
    transport_mode = serializers.ChoiceField(choices=EWayBill.Mode.choices)
    vehicle_number = serializers.CharField(allow_blank=True)
    transporter_id = serializers.CharField(allow_blank=True)
    transporter_name = serializers.CharField(allow_blank=True)
    transport_doc_no = serializers.CharField(allow_blank=True)
    transport_doc_date = serializers.DateField(allow_null=True)
    distance_km = serializers.IntegerField(allow_null=True)
    error_code = serializers.CharField(allow_blank=True)
    error_message = serializers.CharField(allow_blank=True)
    retryable = serializers.BooleanField()
    attempts = serializers.IntegerField()
    requested_at = serializers.DateTimeField(allow_null=True)
    next_retry_at = serializers.DateTimeField(allow_null=True)
    generated_at = serializers.DateTimeField(allow_null=True)
    cancelled_at = serializers.DateTimeField(allow_null=True)
    can_request = serializers.BooleanField(help_text='"Make e-way bill" or "Try again".')
    can_update = serializers.BooleanField(help_text="A new vehicle (Part-B) can be given.")
    can_cancel = serializers.BooleanField(help_text="Within the cancellation window.")
    cancel_until = serializers.DateTimeField(allow_null=True)
    pending_update = serializers.CharField(
        allow_blank=True, help_text="PART_B or CANCEL while one is being sent."
    )
    last_update_error = serializers.CharField(allow_blank=True)
    last_update_error_code = serializers.CharField(
        allow_blank=True, help_text="Why the last change failed, as a code (shown translated)."
    )


class EWayBillUpdateRowSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=EWayBillUpdate.Kind.choices)
    status = serializers.ChoiceField(choices=EWayBillUpdate.Status.choices)
    vehicle_number = serializers.CharField(allow_blank=True)
    reason_code = serializers.CharField()
    remarks = serializers.CharField(allow_blank=True)
    error_code = serializers.CharField(allow_blank=True)
    error_message = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    done_at = serializers.DateTimeField(allow_null=True)


class EWayBillRowSerializer(EWayBillSummarySerializer):
    invoice_id = serializers.UUIDField()
    invoice_number = serializers.CharField()
    invoice_date = serializers.DateField()
    shop_name = serializers.CharField()
    retailer_id = serializers.UUIDField()
    shipment_number = serializers.CharField()
    updates = EWayBillUpdateRowSerializer(many=True)


class TransportInputSerializer(serializers.Serializer[Any]):
    transport_mode = serializers.ChoiceField(
        choices=EWayBill.Mode.choices, default=EWayBill.Mode.ROAD
    )
    vehicle_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    transporter_id = serializers.CharField(max_length=15, required=False, allow_blank=True)
    transporter_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    transport_doc_no = serializers.CharField(max_length=40, required=False, allow_blank=True)
    transport_doc_date = serializers.DateField(required=False, allow_null=True)
    distance_km = serializers.IntegerField(min_value=1, max_value=4000, required=False)


class PartBInputSerializer(serializers.Serializer[Any]):
    vehicle_number = serializers.CharField(max_length=20)
    transport_doc_no = serializers.CharField(max_length=40, required=False, allow_blank=True)
    reason_code = serializers.ChoiceField(choices=list(PART_B_REASONS.items()))
    remarks = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class EWayBillCancelSerializer(serializers.Serializer[Any]):
    reason_code = serializers.ChoiceField(choices=list(CANCEL_REASONS.items()))
    remarks = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class EWayBillCountsSerializer(serializers.Serializer[Any]):
    pending = serializers.IntegerField()
    failed = serializers.IntegerField()
