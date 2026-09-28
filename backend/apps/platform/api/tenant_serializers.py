"""The distributor's settings API (PLAN §3.4)."""

from typing import Any

from rest_framework import serializers


class BusinessSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=200)
    legal_name = serializers.CharField(max_length=200)
    gstin = serializers.CharField(max_length=30)  # spaces are removed by the service
    pan = serializers.CharField(max_length=10, read_only=True)
    state_code = serializers.CharField(max_length=2)
    registration_type = serializers.CharField(read_only=True)
    slug = serializers.CharField(read_only=True, help_text="Changed only by the platform team.")
    address_line1 = serializers.CharField(max_length=200)
    address_line2 = serializers.CharField(max_length=200, allow_blank=True)
    city = serializers.CharField(max_length=100)
    pincode = serializers.CharField(max_length=6)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=16)
    invoice_terms = serializers.CharField(allow_blank=True)
    invoice_footer = serializers.CharField(allow_blank=True)
    signatory_name = serializers.CharField(max_length=150, allow_blank=True)
    has_signatory_image = serializers.BooleanField(read_only=True)
    gst_identity_locked = serializers.BooleanField(
        read_only=True,
        help_text="After the first invoice the GSTIN, legal name and state are read-only.",
    )


class BankDetailsSerializer(serializers.Serializer[Any]):
    bank_account_name = serializers.CharField(max_length=200, allow_blank=True)
    bank_account_number_masked = serializers.CharField(read_only=True)
    bank_ifsc = serializers.CharField(max_length=11, allow_blank=True)
    bank_name = serializers.CharField(max_length=120, allow_blank=True)
    bank_branch = serializers.CharField(max_length=120, allow_blank=True)
    upi_id = serializers.CharField(max_length=320, allow_blank=True)


class BankDetailsInputSerializer(serializers.Serializer[Any]):
    bank_account_name = serializers.CharField(max_length=200, allow_blank=True, required=False)
    bank_account_number = serializers.CharField(
        max_length=20, allow_blank=True, required=False, write_only=True
    )
    bank_ifsc = serializers.CharField(max_length=11, allow_blank=True, required=False)
    bank_name = serializers.CharField(max_length=120, allow_blank=True, required=False)
    bank_branch = serializers.CharField(max_length=120, allow_blank=True, required=False)
    upi_id = serializers.CharField(max_length=320, allow_blank=True, required=False)


class BrandingSerializer(serializers.Serializer[Any]):
    display_name = serializers.CharField(max_length=120, allow_blank=True)
    primary_color = serializers.CharField(max_length=7)
    logo_url = serializers.CharField(allow_null=True, read_only=True)
    favicon_url = serializers.CharField(allow_null=True, read_only=True)
    app_icon_url = serializers.CharField(allow_null=True, read_only=True)


class PublicBrandingSerializer(serializers.Serializer[Any]):
    slug = serializers.CharField()
    display_name = serializers.CharField()
    primary_color = serializers.CharField()
    available = serializers.BooleanField(
        help_text="False for any state other than active: show the neutral 'unavailable' message."
    )
    logo_url = serializers.CharField(allow_null=True)
    favicon_url = serializers.CharField(allow_null=True)
    app_icon_url = serializers.CharField(allow_null=True)


class AssetUploadSerializer(serializers.Serializer[Any]):
    file = serializers.FileField()


class TenantFeatureSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    enabled = serializers.BooleanField()
    tenant_toggleable = serializers.BooleanField()
