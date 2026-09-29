from typing import Any

from rest_framework import serializers

from apps.compliance.models import GstCredential
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
