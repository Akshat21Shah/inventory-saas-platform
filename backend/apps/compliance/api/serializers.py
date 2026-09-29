from typing import Any

from rest_framework import serializers

from apps.compliance.models import CancelReason, DocumentType, EInvoiceRecord, GstCredential
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
    can_cancel = serializers.BooleanField(help_text="An invoice's IRN within the window.")
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


class EInvoiceCountsSerializer(serializers.Serializer[Any]):
    pending = serializers.IntegerField()
    failed = serializers.IntegerField()
    near_report_by = serializers.IntegerField(
        help_text="Still without an IRN, 3 days or less from the reporting limit."
    )
