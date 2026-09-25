from typing import Any

from rest_framework import serializers

from apps.accounts.models import LANGUAGE_CHOICES as LANGUAGES
from apps.retailers.models import Retailer, RetailerAddress


class PersonRefSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    full_name = serializers.CharField()


class AddressSerializer(serializers.ModelSerializer[RetailerAddress]):
    state_code = serializers.CharField(source="state_id", read_only=True)

    class Meta:
        model = RetailerAddress
        fields = (
            "id",
            "kind",
            "label",
            "line1",
            "line2",
            "city",
            "district",
            "pincode",
            "state_code",
            "is_default",
        )
        read_only_fields = fields


class AddressWriteSerializer(serializers.Serializer[Any]):
    kind = serializers.ChoiceField(choices=RetailerAddress.Kind.choices)
    # A DRF field may be called "label" (the attribute is only a class-level default for mypy).
    label = serializers.CharField(  # type: ignore[assignment]
        max_length=60, required=False, allow_blank=True, default=""
    )
    line1 = serializers.CharField(max_length=200)
    line2 = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=100)
    district = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    pincode = serializers.CharField(max_length=10)
    state_code = serializers.CharField(max_length=2)
    is_default = serializers.BooleanField(required=False, allow_null=True, default=None)


class BillingAddressSerializer(serializers.Serializer[Any]):
    line1 = serializers.CharField(max_length=200)
    line2 = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=100)
    district = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    pincode = serializers.CharField(max_length=10)
    state_code = serializers.CharField(max_length=2)


class RetailerListSerializer(serializers.ModelSerializer[Retailer]):
    state_code = serializers.CharField(source="state_id", read_only=True)
    salesperson = PersonRefSerializer(allow_null=True, read_only=True)

    class Meta:
        model = Retailer
        fields = (
            "id",
            "code",
            "shop_name",
            "owner_name",
            "mobile",
            "gstin",
            "state_code",
            "status",
            "salesperson",
            "credit_limit",
            "payment_terms_days",
            "tags",
        )
        read_only_fields = fields


class RetailerDetailSerializer(serializers.ModelSerializer[Retailer]):
    state_code = serializers.CharField(source="state_id", read_only=True)
    salesperson = PersonRefSerializer(allow_null=True, read_only=True)
    addresses = AddressSerializer(many=True, read_only=True)

    class Meta:
        model = Retailer
        fields = (
            "id",
            "code",
            "shop_name",
            "owner_name",
            "mobile",
            "email",
            "gstin",
            "pan",
            "state_code",
            "status",
            "blocked_reason",
            "salesperson",
            "credit_limit",
            "payment_terms_days",
            "notes",
            "tags",
            "preferred_language",
            "welcome_sent_at",
            "addresses",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class RetailerWriteSerializer(serializers.Serializer[Any]):
    shop_name = serializers.CharField(max_length=200)
    mobile = serializers.CharField(max_length=20)
    owner_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    gstin = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    state_code = serializers.CharField(max_length=2, required=False, allow_blank=True, default="")
    salesperson = serializers.UUIDField(required=False, allow_null=True, default=None)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    tags = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False, default=list
    )
    preferred_language = serializers.ChoiceField(
        choices=["en", "hi", "mr"], required=False, default="en"
    )
    billing_address = BillingAddressSerializer(required=False, allow_null=True, default=None)


class RetailerUpdateSerializer(serializers.Serializer[Any]):
    shop_name = serializers.CharField(max_length=200, required=False)
    mobile = serializers.CharField(max_length=20, required=False)
    owner_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    gstin = serializers.CharField(max_length=30, required=False, allow_blank=True)
    state_code = serializers.CharField(max_length=2, required=False)
    salesperson = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    tags = serializers.ListField(child=serializers.CharField(max_length=40), required=False)
    preferred_language = serializers.ChoiceField(choices=LANGUAGES, required=False)


class CreditSerializer(serializers.Serializer[Any]):
    credit_limit = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    payment_terms_days = serializers.IntegerField(min_value=0, max_value=365)


class BlockSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(max_length=300)


class RetailerFilterSerializer(serializers.Serializer[Any]):
    search = serializers.CharField(required=False, allow_blank=True, default="")
    status = serializers.ChoiceField(choices=Retailer.Status.choices, required=False, default="")
    salesperson = serializers.UUIDField(required=False)
    state = serializers.CharField(max_length=2, required=False, default="")
    tag = serializers.CharField(max_length=40, required=False, default="")


class RetailerBulkSerializer(serializers.Serializer[Any]):
    retailer_ids = serializers.ListField(child=serializers.UUIDField(), max_length=1000)
    action = serializers.ChoiceField(choices=["assign_salesperson", "block", "unblock"])
    value = serializers.CharField(required=False, allow_null=True, allow_blank=True, default=None)


class RetailerBulkResultSerializer(serializers.Serializer[Any]):
    changed = serializers.IntegerField()


class SalespersonSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(source="user.id")
    full_name = serializers.CharField(source="user.full_name")
    email = serializers.EmailField(source="user.email")
