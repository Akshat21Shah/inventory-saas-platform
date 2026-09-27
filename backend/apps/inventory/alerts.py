"""Stock alerts (PLAN §5.4, spec 5.7): evaluated in the same transaction as each stock change.

- OUT_OF_STOCK is open while available ≤ 0.
- LOW_STOCK is open while 0 < available ≤ the reorder level (never with a reorder level of 0).
- BACKORDER_DEMAND is open while shops are waiting (backordered > 0; Phase 4 sets that).

The partial unique index allows one open alert per product, warehouse and type, and opening uses
``ON CONFLICT DO NOTHING``, so an alert fires once until it is resolved. An outbox event is written
only when a row is actually opened or resolved.
"""

from decimal import Decimal
from uuid import UUID

from django.db import connection
from django.utils import timezone

from apps.catalog.models import Product
from apps.inventory.models import StockAlert, StockLevel
from common import outbox
from common.ids import uuid7
from common.tenancy import require_tenant_id

OPENED = "stock.alert_opened"
RESOLVED = "stock.alert_resolved"


def wanted(level: StockLevel, reorder_level: Decimal) -> dict[str, Decimal]:
    """The alert types that should be open for this level, with the value that triggers each."""
    available = level.quantity_on_hand - level.quantity_reserved
    result: dict[str, Decimal] = {}
    if available <= 0:
        result[StockAlert.Type.OUT_OF_STOCK] = available
    elif reorder_level > 0 and available <= reorder_level:
        result[StockAlert.Type.LOW_STOCK] = available
    if level.quantity_backordered > 0:
        result[StockAlert.Type.BACKORDER_DEMAND] = level.quantity_backordered
    return result


def evaluate(level: StockLevel, reorder_level: Decimal | None = None) -> None:
    """Open and resolve this level's alerts. Call with the level locked, inside the transaction."""
    if reorder_level is None:
        reorder_level = Product.objects.filter(pk=level.product_id).values_list(
            "reorder_level", flat=True
        )[0]
    want = wanted(level, Decimal(reorder_level))
    open_types = set(
        StockAlert.objects.filter(
            product_id=level.product_id, warehouse_id=level.warehouse_id, status="OPEN"
        ).values_list("alert_type", flat=True)
    )
    for alert_type in sorted(set(want) - open_types):
        _open(level, alert_type, want[alert_type])
    for alert_type in sorted(open_types - set(want)):
        _resolve(level, alert_type)


def _payload(level: StockLevel, alert_type: str) -> dict[str, str]:
    return {
        "product_id": str(level.product_id),
        "warehouse_id": str(level.warehouse_id),
        "alert_type": alert_type,
        "available": str(level.quantity_on_hand - level.quantity_reserved),
    }


def _open(level: StockLevel, alert_type: str, value: Decimal) -> None:
    table = StockAlert._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {table} "  # noqa: S608
            "(id, tenant_id, product_id, warehouse_id, alert_type, status, opened_at, "
            "value_at_open, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, 'OPEN', %s, %s, now(), now()) "
            "ON CONFLICT (tenant_id, product_id, warehouse_id, alert_type) "
            "WHERE status = 'OPEN' DO NOTHING RETURNING id",
            [
                uuid7(),
                require_tenant_id(),
                level.product_id,
                level.warehouse_id,
                alert_type,
                timezone.now(),
                value,
            ],
        )
        row = cursor.fetchone()
    if row is not None:
        _emit(OPENED, row[0], level, alert_type)


def _resolve(level: StockLevel, alert_type: str) -> None:
    resolved = list(
        StockAlert.objects.filter(
            product_id=level.product_id,
            warehouse_id=level.warehouse_id,
            alert_type=alert_type,
            status="OPEN",
        )
        .select_for_update()
        .values_list("id", flat=True)
    )
    if not resolved:
        return
    StockAlert.objects.filter(pk__in=resolved, status="OPEN").update(
        status="RESOLVED", resolved_at=timezone.now(), updated_at=timezone.now()
    )
    for alert_id in resolved:
        _emit(RESOLVED, alert_id, level, alert_type)


def _emit(event_type: str, alert_id: UUID, level: StockLevel, alert_type: str) -> None:
    outbox.emit(
        event_type,
        aggregate_type="StockAlert",
        aggregate_id=alert_id,
        payload=_payload(level, alert_type),
    )
