from typing import Any

from rest_framework import serializers

from apps.compliance.models import DocumentType, EInvoiceRecord, GstCredential
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


class EInvoiceCountsSerializer(serializers.Serializer[Any]):
    pending = serializers.IntegerField()
    failed = serializers.IntegerField()
    near_report_by = serializers.IntegerField(
        help_text="Still without an IRN, 3 days or less from the reporting limit."
    )
