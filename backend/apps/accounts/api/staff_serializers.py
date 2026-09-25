"""Staff management serializers (PLAN §3.4)."""

from typing import Any

from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import Invitation, Membership, Role


class RoleRefSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    name = serializers.CharField()


class StaffUserSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    full_name = serializers.CharField()
    mfa_enabled = serializers.BooleanField(source="totp_enabled")
    last_login = serializers.DateTimeField(allow_null=True)


class MembershipSerializer(serializers.ModelSerializer[Membership]):
    user = StaffUserSerializer()
    role = RoleRefSerializer()

    class Meta:
        model = Membership
        fields = ["id", "user", "role", "is_active", "joined_at"]


class MembershipUpdateSerializer(serializers.Serializer[Any]):
    role_code = serializers.CharField(max_length=40, required=False)
    is_active = serializers.BooleanField(required=False)


class InvitationSerializer(serializers.ModelSerializer[Invitation]):
    role = RoleRefSerializer()
    status = serializers.SerializerMethodField()
    invited_by = serializers.SerializerMethodField()

    class Meta:
        model = Invitation
        fields = ["id", "email", "role", "status", "expires_at", "invited_by", "created_at"]

    def get_status(self, obj: Invitation) -> str:
        if obj.status == Invitation.Status.PENDING and obj.expires_at <= timezone.now():
            return Invitation.Status.EXPIRED.value
        return obj.status

    def get_invited_by(self, obj: Invitation) -> str:
        return obj.invited_by.full_name if obj.invited_by else ""


class InvitationCreateSerializer(serializers.Serializer[Any]):
    email = serializers.EmailField()
    role_code = serializers.CharField(max_length=40)


class RoleSerializer(serializers.ModelSerializer[Role]):
    permissions: "serializers.SlugRelatedField[Any]" = serializers.SlugRelatedField(
        slug_field="code", many=True, read_only=True
    )

    class Meta:
        model = Role
        fields = ["id", "code", "name", "is_system", "permissions"]


class PermissionSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    module = serializers.CharField()
    description = serializers.CharField()


class InvitationTokenSerializer(serializers.Serializer[Any]):
    token = serializers.CharField(max_length=200)


class InvitationPreviewSerializer(serializers.Serializer[Any]):
    tenant_name = serializers.CharField()
    email = serializers.EmailField()
    role = RoleRefSerializer()
    invited_by = serializers.CharField(allow_blank=True)
    existing_account = serializers.BooleanField(
        help_text="True: ask for the existing password instead of creating one."
    )
    expires_at = serializers.DateTimeField()


class InvitationAcceptSerializer(serializers.Serializer[Any]):
    token = serializers.CharField(max_length=200)
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    password = serializers.CharField(max_length=256, trim_whitespace=False)
