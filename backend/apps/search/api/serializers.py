from rest_framework import serializers

from apps.search.sources import TYPES

HIT_TYPES = [*TYPES, "tenant"]


class SearchHitSerializer(serializers.Serializer[object]):
    type = serializers.ChoiceField(choices=HIT_TYPES)
    id = serializers.UUIDField()
    title = serializers.CharField(help_text="The record's number or name; empty for a draft.")
    detail = serializers.CharField(help_text="The shop, supplier, code or owner it belongs to.")
    date = serializers.DateField(allow_null=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    status = serializers.CharField(help_text="The record's status code, worded by the app.")


class SearchGroupSerializer(serializers.Serializer[object]):
    type = serializers.ChoiceField(choices=HIT_TYPES)
    hits = SearchHitSerializer(many=True)
    more = serializers.BooleanField(help_text="More matches than shown: offer the full list.")


class SearchResultsSerializer(serializers.Serializer[object]):
    query = serializers.CharField(help_text="What was searched, tidied.")
    jump = SearchHitSerializer(
        allow_null=True, help_text="The one record a typed number, GSTIN, mobile or barcode names."
    )
    groups = SearchGroupSerializer(many=True)


class UserHitSerializer(serializers.Serializer[object]):
    kind = serializers.ChoiceField(choices=["STAFF", "SHOP"])
    id = serializers.UUIDField(help_text="The staff membership or the shop's login.")
    name = serializers.CharField()
    email = serializers.CharField()
    phone = serializers.CharField()
    tenant_id = serializers.UUIDField()
    tenant_name = serializers.CharField()
    shop_name = serializers.CharField()
    is_active = serializers.BooleanField()
