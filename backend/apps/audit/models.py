"""Audit log (spec 5.16, PLAN §2.14). Append-only: the database rejects UPDATE and DELETE.

``tenant`` is NULL for platform-level entries (e.g. a GST rate change). RLS: the runtime role reads
only its own tenant's rows and may insert platform rows it can never read back; the platform audit
view reads through the platform (BYPASSRLS) alias.
"""

from django.conf import settings
from django.contrib.postgres.indexes import BrinIndex
from django.db import models

from common.models import BaseModel


class AuditLog(BaseModel):
    class ActorType(models.TextChoices):
        PLATFORM = "PLATFORM", "Platform"
        STAFF = "STAFF", "Staff"
        RETAILER = "RETAILER", "Retailer"
        SYSTEM = "SYSTEM", "System"

    tenant = models.ForeignKey(
        "platform.Tenant", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    actor_type = models.CharField(max_length=10, choices=ActorType.choices)
    impersonator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    # FK added with ImpersonationSession (Phase 1 impersonation commit); a plain id until then.
    impersonation_session_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(max_length=80)  # e.g. "settings.changed", "tenant.suspended"
    target_type = models.CharField(max_length=80, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    target_repr = models.CharField(max_length=200, blank=True, default="")
    changes = models.JSONField(default=dict, blank=True)  # {field: [before, after]}
    metadata = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")
    request_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "-created_at"], name="audit_tenant_created_idx"),
            models.Index(
                fields=["tenant", "target_type", "target_id"], name="audit_tenant_target_idx"
            ),
            models.Index(fields=["actor", "created_at"], name="audit_actor_created_idx"),
            models.Index(
                fields=["tenant", "action", "-created_at"], name="audit_tenant_action_idx"
            ),
            BrinIndex(fields=["created_at"], name="audit_created_brin"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(actor_type__in=["PLATFORM", "STAFF", "RETAILER", "SYSTEM"]),
                name="audit_actor_type_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(actor__isnull=False) | models.Q(actor_type="SYSTEM"),
                name="audit_actor_required_unless_system",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.target_type}:{self.target_id}"
