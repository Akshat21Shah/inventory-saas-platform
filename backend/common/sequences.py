"""Gap-free per-tenant counters, allocated under a row lock inside the caller's transaction."""

from django.db import connection, transaction

from common.ids import uuid7
from common.models import Sequence
from common.tenancy import require_tenant_id


def next_value(name: str, period: str) -> int:
    """Return the next number for (tenant, name, period). Rolls back with the caller: no gaps."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("next_value() must run inside the business transaction")
    tenant_id = require_tenant_id()
    table = Sequence._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {table} "  # noqa: S608
            "(id, tenant_id, name, period, next_value, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, 1, now(), now()) "
            "ON CONFLICT (tenant_id, name, period) DO NOTHING",
            [uuid7(), tenant_id, name, period],
        )
    seq = Sequence.objects.select_for_update().get(name=name, period=period)
    value = int(seq.next_value)
    seq.next_value = value + 1
    seq.save(update_fields=["next_value", "updated_at"])
    return value
