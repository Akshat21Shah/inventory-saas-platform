"""Auth API serializers: input validation and response shapes (documented in OpenAPI)."""

from typing import Any

from rest_framework import serializers

from apps.accounts.models import User


class StaffLoginInputSerializer(serializers.Serializer[Any]):
    email = serializers.CharField(max_length=254)
    password = serializers.CharField(max_length=256, trim_whitespace=False)


class TenantChoiceSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()


class HandoffSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    tenant_slug = serializers.CharField()


class LoginResponseSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=["authenticated", "handoff", "choose_tenant"])
    access = serializers.CharField(required=False)
    access_expires_at = serializers.DateTimeField(required=False)
    handoff = HandoffSerializer(required=False)
    choice_token = serializers.CharField(required=False)
    tenants = TenantChoiceSerializer(many=True, required=False)


class ChooseTenantInputSerializer(serializers.Serializer[Any]):
    choice_token = serializers.CharField(max_length=200)
    tenant_id = serializers.UUIDField()


class HandoffExchangeInputSerializer(serializers.Serializer[Any]):
    code = serializers.CharField(max_length=200)


class RefreshInputSerializer(serializers.Serializer[Any]):
    refresh = serializers.CharField(required=False, max_length=2000)


class TokenResponseSerializer(serializers.Serializer[Any]):
    access = serializers.CharField()
    access_expires_at = serializers.DateTimeField()
    refresh = serializers.CharField(required=False, help_text="Only when the request sent one.")


class MeTenantSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    status = serializers.CharField()


class MeRoleSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    name = serializers.CharField()


class MeImpersonationSerializer(serializers.Serializer[Any]):
    session_id = serializers.UUIDField()
    impersonator_id = serializers.UUIDField()
    mode = serializers.CharField()


class MeSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    user_type = serializers.ChoiceField(choices=User.UserType.choices)
    email = serializers.EmailField(allow_null=True)
    phone = serializers.CharField(allow_null=True)
    full_name = serializers.CharField(allow_blank=True)
    preferred_language = serializers.CharField()
    tenant = MeTenantSerializer(allow_null=True)
    role = MeRoleSerializer(allow_null=True)
    permissions = serializers.ListField(child=serializers.CharField())
    features = serializers.DictField(child=serializers.BooleanField())
    impersonation = MeImpersonationSerializer(allow_null=True)


class MeUpdateSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ["full_name", "preferred_language"]
