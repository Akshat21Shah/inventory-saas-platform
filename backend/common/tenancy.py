"""Tenant context (ADR-002).

The current tenant is resolved once per request (from the authenticated user's token) and stored in
a context variable. The same value is pushed into PostgreSQL with ``SET LOCAL`` semantics
(``set_config(..., true)``) so Row-Level Security policies act as a backstop.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from django.db import DatabaseError, connections, transaction

from common.context import tenant_id_var
from common.error_codes import ErrorCode
from common.errors import DomainError

RLS_SETTING = "app.current_tenant"


class TenantContextMissing(DomainError):
    status_code = 500
    code = ErrorCode.TENANT_CONTEXT_MISSING
    default_message = "No tenant is active for this operation."


def get_current_tenant_id() -> UUID | None:
    return tenant_id_var.get()


def require_tenant_id() -> UUID:
    tenant_id = tenant_id_var.get()
    if tenant_id is None:
        raise TenantContextMissing()
    return tenant_id


def set_db_tenant(tenant_id: UUID | None, using: str = "default") -> None:
    """Set the RLS tenant for the current transaction only. Must run inside ``atomic()``."""
    connection = connections[using]
    if not connection.in_atomic_block:
        raise RuntimeError("set_db_tenant() requires an open transaction (SET LOCAL semantics)")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config(%s, %s, true)", [RLS_SETTING, str(tenant_id) if tenant_id else ""]
        )


def activate_tenant(tenant_id: UUID | None) -> None:
    """Set both the context variable and (if inside a transaction) the DB session setting."""
    tenant_id_var.set(tenant_id)
    if connections["default"].in_atomic_block:
        set_db_tenant(tenant_id)


@contextmanager
def tenant_context(tenant_id: UUID) -> Iterator[None]:
    """Temporarily act as ``tenant_id`` (tests, Celery tasks, scripts)."""
    token = tenant_id_var.set(tenant_id)
    previous = None
    connection = connections["default"]
    if connection.in_atomic_block:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting(%s, true)", [RLS_SETTING])
            previous = cursor.fetchone()[0]
        set_db_tenant(tenant_id)
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        tenant_id_var.reset(token)
        if connection.in_atomic_block and previous is not None:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config(%s, %s, true)", [RLS_SETTING, previous])
            except DatabaseError:
                # After a failed body the transaction is usually aborted; its rollback discards the
                # SET LOCAL anyway. Never mask the original error with the restore failure.
                if not failed:
                    raise


@contextmanager
def tenant_transaction(tenant_id: UUID) -> Iterator[None]:
    """A transaction with the RLS tenant set. Use this, not ``tenant_context`` alone, to open a
    transaction inside a non-atomic task: ``tenant_context`` only reaches PostgreSQL when a
    transaction is already open, and without it RLS hides every tenant row from ``app_user``."""
    with transaction.atomic(), tenant_context(tenant_id):
        yield
