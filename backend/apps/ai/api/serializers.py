from typing import Any

from rest_framework import serializers

from apps.ai.models import AiUsage


class AllowanceSerializer(serializers.Serializer[Any]):
    questions = serializers.IntegerField(help_text="About this many assistant questions a month…")
    searches = serializers.IntegerField(help_text="…or about this many shop searches.")
    cost = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="At most about this much a month (all spent on questions), in ₹.",
    )


class FeatureUsageSerializer(serializers.Serializer[Any]):
    feature = serializers.ChoiceField(choices=AiUsage.Feature.choices)
    cost = serializers.DecimalField(max_digits=14, decimal_places=2, help_text="Estimated, in ₹.")
    units = serializers.IntegerField()
    calls = serializers.IntegerField()
    failed = serializers.IntegerField()


class MyAiUsageSerializer(serializers.Serializer[Any]):
    enabled = serializers.BooleanField(help_text="The AI module is on for this business.")
    since = serializers.DateField(help_text="The first day of this month (India time).")
    model = serializers.CharField(help_text="The assistant's model the estimates are priced at.")
    cost = serializers.DecimalField(
        max_digits=14, decimal_places=2, help_text="Estimated cost this month, in ₹."
    )
    questions = serializers.IntegerField(help_text="Questions asked of the assistant this month.")
    searches = serializers.IntegerField(help_text="Shop searches that used AI this month.")
    allowance = AllowanceSerializer(allow_null=True, help_text="Null: no monthly limit.")
    units = serializers.IntegerField(help_text="The provider's units used this month (in and out).")
    limit = serializers.IntegerField(allow_null=True, help_text="Units a month; null: no limit.")
    calls = serializers.IntegerField()
    failed = serializers.IntegerField()
    near_limit = serializers.BooleanField(help_text="At 90% or more of the limit.")
    by_feature = FeatureUsageSerializer(many=True)


class TenantAiUsageSerializer(serializers.Serializer[Any]):
    tenant_id = serializers.UUIDField()
    name = serializers.CharField()
    cost = serializers.DecimalField(
        max_digits=14, decimal_places=2, help_text="Estimated cost this month, in ₹."
    )
    questions = serializers.IntegerField()
    searches = serializers.IntegerField()
    units = serializers.IntegerField(help_text="This month (in and out).")
    calls = serializers.IntegerField()
    failed = serializers.IntegerField()
    near_limit = serializers.BooleanField()


class PlatformAiUsageSerializer(serializers.Serializer[Any]):
    model = serializers.CharField(help_text="The assistant's model the estimates are priced at.")
    limit = serializers.IntegerField(allow_null=True, help_text="Units a month per distributor.")
    allowance = AllowanceSerializer(allow_null=True, help_text="Null: no monthly limit.")
    rows = TenantAiUsageSerializer(many=True, help_text="The dearest first.")
