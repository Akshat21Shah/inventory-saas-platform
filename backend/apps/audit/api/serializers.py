"""Audit log entries as shown to tenant owners and super admins (spec 5.16)."""

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.audit.models import AuditLog


class AuditActorSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    full_name = serializers.CharField()
    email = serializers.CharField(allow_null=True)


class AuditTenantSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    name = serializers.CharField()


class AuditLogSerializer(serializers.ModelSerializer[AuditLog]):
    actor = serializers.SerializerMethodField()
    impersonator = serializers.SerializerMethodField()
    tenant = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "created_at",
            "tenant",
            "actor",
            "actor_type",
            "impersonator",
            "impersonation_session_id",
            "action",
            "target_type",
            "target_id",
            "target_repr",
            "changes",
            "metadata",
            "ip",
            "user_agent",
            "request_id",
        ]

    @staticmethod
    def _person(user: Any) -> dict[str, Any] | None:
        if user is None:
            return None
        return {"id": user.pk, "full_name": user.full_name, "email": user.email}

    @extend_schema_field(AuditActorSerializer(allow_null=True))
    def get_actor(self, obj: AuditLog) -> dict[str, Any] | None:
        return self._person(obj.actor)

    @extend_schema_field(AuditActorSerializer(allow_null=True))
    def get_impersonator(self, obj: AuditLog) -> dict[str, Any] | None:
        return self._person(obj.impersonator)

    @extend_schema_field(AuditTenantSerializer(allow_null=True))
    def get_tenant(self, obj: AuditLog) -> dict[str, Any] | None:
        if obj.tenant_id is None or "tenant" not in obj._state.fields_cache:
            return {"id": obj.tenant_id, "name": ""} if obj.tenant_id else None
        return {"id": obj.tenant_id, "name": obj.tenant.name if obj.tenant else ""}


class AuditFilterSerializer(serializers.Serializer[Any]):
    action = serializers.CharField(required=False, max_length=80)
    actor_id = serializers.UUIDField(required=False)
    target_type = serializers.CharField(required=False, max_length=80)
    target_id = serializers.CharField(required=False, max_length=64)
    since = serializers.DateTimeField(required=False)
    until = serializers.DateTimeField(required=False)
    tenant_id = serializers.UUIDField(required=False)
