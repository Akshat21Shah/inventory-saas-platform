"""Base models. Tenant-owned models inherit ``TenantScopedModel`` (CLAUDE.md §4, ADR-002)."""

from typing import Any, ClassVar

from django.conf import settings
from django.db import models

from common.error_codes import ErrorCode
from common.errors import DomainError
from common.ids import uuid7
from common.tenancy import require_tenant_id


class BaseModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class CrossTenantWrite(DomainError):
    status_code = 403
    code = ErrorCode.CROSS_TENANT_ACCESS
    default_message = "This record belongs to a different workspace."


class TenantManager[M: models.Model](models.Manager[M]):
    """Default manager: always filtered by the active tenant; fails closed when none is active."""

    def get_queryset(self) -> models.QuerySet[M]:
        return super().get_queryset().filter(tenant_id=require_tenant_id())

    def unscoped(self) -> models.QuerySet[M]:
        """Cross-tenant queryset. Only for audited platform code paths (ADR-002)."""
        return super().get_queryset()


class TenantScopedModel(BaseModel):
    tenant = models.ForeignKey(
        "platform.Tenant", on_delete=models.PROTECT, related_name="+", editable=False
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )

    objects: ClassVar[TenantManager[Any]] = TenantManager()

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        active = require_tenant_id()
        if self.tenant_id is None:
            self.tenant_id = active
        elif self.tenant_id != active:
            raise CrossTenantWrite()
        super().save(*args, **kwargs)


class SoftDeleteMixin(models.Model):
    """Soft delete for master data only — never for financial or stock records."""

    is_active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


# --- Infrastructure models ---------------------------------------------------------------------


class Sequence(TenantScopedModel):
    """Per-tenant counters for human-facing numbers (orders, GRNs, receipts…).

    Invoice numbering uses ``billing.InvoiceSeries`` (configurable prefix, per FY) in Phase 5.
    """

    name = models.CharField(max_length=40)
    period = models.CharField(max_length=10)
    next_value = models.BigIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name", "period"], name="uniq_sequence_per_period"
            ),
            models.CheckConstraint(
                condition=models.Q(next_value__gte=1), name="sequence_next_value_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name}/{self.period}={self.next_value}"


class IdempotencyRecord(BaseModel):
    """Stored result of an idempotent request (ADR-005). Not tenant-scoped: keyed by user."""

    tenant = models.ForeignKey(
        "platform.Tenant", on_delete=models.CASCADE, null=True, related_name="+"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    scope = models.CharField(max_length=80)
    key = models.CharField(max_length=80)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField(null=True)
    response_body = models.JSONField(null=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "scope", "key"], name="uniq_idempotency_key"),
        ]

    def __str__(self) -> str:
        return f"{self.scope}:{self.key}"


class OutboxEvent(BaseModel):
    """Transactional outbox (ADR-003). Not RLS-protected: the dispatcher reads across tenants.

    Payloads carry identifiers only; consumers load data inside the tenant's context.
    """

    tenant = models.ForeignKey(
        "platform.Tenant", on_delete=models.PROTECT, null=True, related_name="+"
    )
    event_type = models.CharField(max_length=80)
    aggregate_type = models.CharField(max_length=80)
    aggregate_id = models.UUIDField()
    payload = models.JSONField(default=dict)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(
                fields=["created_at"],
                name="outbox_pending_idx",
                condition=models.Q(dispatched_at__isnull=True),
            ),
            models.Index(fields=["tenant", "created_at"], name="outbox_tenant_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.event_type}({self.aggregate_type}:{self.aggregate_id})"
