from typing import Any

from rest_framework import serializers

from apps.ai.models import AiUsage


class FeatureUsageSerializer(serializers.Serializer[Any]):
    feature = serializers.ChoiceField(choices=AiUsage.Feature.choices)
    units = serializers.IntegerField()
    calls = serializers.IntegerField()
    failed = serializers.IntegerField()


class MyAiUsageSerializer(serializers.Serializer[Any]):
    enabled = serializers.BooleanField(help_text="The AI module is on for this business.")
    since = serializers.DateField(help_text="The first day of this month (India time).")
    units = serializers.IntegerField(help_text="Units used this month (in and out).")
    limit = serializers.IntegerField(allow_null=True, help_text="Units a month; null: no limit.")
    calls = serializers.IntegerField()
    failed = serializers.IntegerField()
    near_limit = serializers.BooleanField(help_text="At 90% or more of the limit.")
    by_feature = FeatureUsageSerializer(many=True)


class TenantAiUsageSerializer(serializers.Serializer[Any]):
    tenant_id = serializers.UUIDField()
    name = serializers.CharField()
    units = serializers.IntegerField(help_text="This month (in and out).")
    calls = serializers.IntegerField()
    failed = serializers.IntegerField()
    limit = serializers.IntegerField(allow_null=True, help_text="Null: no limit.")
    near_limit = serializers.BooleanField()
