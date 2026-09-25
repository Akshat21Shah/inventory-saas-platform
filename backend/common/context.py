"""Request-scoped context variables used by logging, tenancy and the audit log."""

from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
tenant_id_var: ContextVar[UUID | None] = ContextVar("tenant_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)


@dataclass(frozen=True)
class RequestMeta:
    ip: str | None
    user_agent: str


@dataclass(frozen=True)
class Actor:
    """Who is acting. ``impersonator_id`` is set when a super admin acts as ``user_id``."""

    user_id: UUID
    actor_type: str  # PLATFORM | STAFF | RETAILER (audit.AuditLog.ActorType)
    impersonator_id: UUID | None = None
    impersonation_session_id: UUID | None = None


request_meta_var: ContextVar[RequestMeta | None] = ContextVar("request_meta", default=None)
actor_var: ContextVar[Actor | None] = ContextVar("actor", default=None)
