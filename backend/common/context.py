"""Request-scoped context variables (request id, tenant id, user id) used by logging and tenancy."""

from contextvars import ContextVar
from uuid import UUID

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
tenant_id_var: ContextVar[UUID | None] = ContextVar("tenant_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
