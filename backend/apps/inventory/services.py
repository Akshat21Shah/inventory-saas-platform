"""Inventory write logic (PLAN §5, ADR-041). Every stock change goes through this module.

Rules (PLAN §5.1, level L3):
- Stock rows are locked with ``lock_levels`` (``select_for_update`` ordered by product, warehouse)
  inside the caller's ``transaction.atomic()``; anything locked before them sits higher in the
  global lock order, anything after (products for the cost price, sequences) lower.
- ``_apply_movement`` is the only code that changes a stock level. It writes the movement row with
  the balances afterwards in the same transaction; the database checks are the last defence.
- The direction of each movement type lives in ``MOVEMENT_KINDS``; a new type (manufacturing's
  CONSUME / PRODUCE) is one more row there (ADR-041).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import connection, transaction

from apps.accounts.models import User
from apps.audit import services as audit
from apps.billing.tax import round2, stock_value, weighted_average_cost
from apps.catalog.models import Product
from apps.inventory import alerts
from apps.inventory.defaults import ensure_default_warehouse
from apps.inventory.models import MovementType, StockLevel, StockMovement, Warehouse
from apps.platform.selectors import get_setting
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields, NotFound
from common.ids import uuid7
from common.tenancy import require_tenant_id

ZERO = Decimal("0")


class InsufficientStock(DomainError):
    status_code = 409
    code = ErrorCode.INSUFFICIENT_STOCK
    default_message = "There isn't enough stock."


class StockReserved(DomainError):
    status_code = 409
    code = ErrorCode.STOCK_RESERVED
    default_message = "This stock is reserved for orders and can't be removed."


@dataclass(frozen=True)
class Direction:
    """How a movement of ``quantity`` changes on hand and reserved: -1, 0 or +1 each."""

    on_hand: int
    reserved: int


MOVEMENT_KINDS: dict[str, Direction] = {
    MovementType.INWARD: Direction(+1, 0),
    MovementType.RETURN: Direction(+1, 0),
    MovementType.ADJUSTMENT_IN: Direction(+1, 0),
    MovementType.TRANSFER_IN: Direction(+1, 0),
    MovementType.ADJUSTMENT_OUT: Direction(-1, 0),
    MovementType.DAMAGE: Direction(-1, 0),
    MovementType.TRANSFER_OUT: Direction(-1, 0),
    MovementType.SALE: Direction(-1, -1),  # dispatch consumes a reservation (Phase 4)
    MovementType.RESERVE: Direction(0, +1),
    MovementType.RELEASE: Direction(0, -1),
}


@dataclass(frozen=True)
class Ref:
    """The document behind a movement."""

    type: str
    id: UUID
    number: str = ""


def default_warehouse() -> Warehouse:
    """The active tenant's default warehouse (created on first use for safety)."""
    warehouse: Warehouse = ensure_default_warehouse(Warehouse)
    return warehouse


def ensure_levels_exist(product_ids: Iterable[UUID], warehouse: Warehouse) -> None:
    """Create any missing stock level at zero (PLAN S6); safe under concurrency."""
    ids = sorted(set(product_ids))
    if not ids:
        return
    tenant_id = require_tenant_id()
    table = StockLevel._meta.db_table
    rows = [(uuid7(), tenant_id, product_id, warehouse.pk) for product_id in ids]
    with connection.cursor() as cursor:
        cursor.executemany(
            f"INSERT INTO {table} "  # noqa: S608
            "(id, tenant_id, product_id, warehouse_id, quantity_on_hand, quantity_reserved, "
            "quantity_backordered, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, 0, 0, 0, now(), now()) "
            "ON CONFLICT (product_id, warehouse_id) DO NOTHING",
            rows,
        )


def lock_levels(product_ids: Iterable[UUID], warehouse: Warehouse) -> dict[UUID, StockLevel]:
    """Lock the stock rows of these products in one warehouse, always in product order (L3)."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("lock_levels() must run inside the business transaction")
    ids = sorted(set(product_ids))
    ensure_levels_exist(ids, warehouse)
    rows = (
        StockLevel.objects.select_for_update()
        .filter(warehouse=warehouse, product_id__in=ids)
        .order_by("product_id", "warehouse_id")
    )
    return {row.product_id: row for row in rows}


def _apply_movement(
    level: StockLevel,
    movement_type: str,
    quantity: Decimal,
    ref: Ref,
    *,
    by: User | None,
    unit_cost: Decimal | None = None,
    reason: str = "",
) -> StockMovement:
    """Change one locked stock level and record the movement. The only writer of stock levels."""
    if quantity <= 0:
        raise ValueError("a movement quantity must be above zero")
    direction = MOVEMENT_KINDS[movement_type]
    delta_on_hand = quantity * direction.on_hand
    delta_reserved = quantity * direction.reserved
    on_hand = level.quantity_on_hand + delta_on_hand
    reserved = level.quantity_reserved + delta_reserved
    if reserved < 0:
        raise ValueError("cannot release more than is reserved")
    available = level.quantity_on_hand - level.quantity_reserved
    if on_hand < 0 or (direction.reserved > 0 and reserved > on_hand):
        raise InsufficientStock(
            details={"product_id": str(level.product_id), "available": str(available)}
        )
    if reserved > on_hand:
        raise StockReserved(
            details={"product_id": str(level.product_id), "available": str(available)}
        )
    level.quantity_on_hand, level.quantity_reserved = on_hand, reserved
    level.save(update_fields=["quantity_on_hand", "quantity_reserved", "updated_at"])
    movement: StockMovement = StockMovement.objects.create(
        product_id=level.product_id,
        warehouse_id=level.warehouse_id,
        movement_type=movement_type,
        quantity=quantity,
        delta_on_hand=delta_on_hand,
        delta_reserved=delta_reserved,
        on_hand_after=on_hand,
        reserved_after=reserved,
        unit_cost=unit_cost,
        value=None if unit_cost is None else stock_value(quantity, unit_cost),
        reference_type=ref.type,
        reference_id=ref.id,
        reference_number=ref.number,
        reason=reason,
        created_by=by,
    )
    alerts.evaluate(level)
    return movement


def refresh_alerts(product_ids: Iterable[UUID], warehouse: Warehouse | None = None) -> None:
    """Re-check alerts without a stock change (e.g. after a reorder level changes)."""
    levels = lock_levels(product_ids, warehouse or default_warehouse())
    for level in levels.values():
        alerts.evaluate(level)


# --- Primitives for other services (receipts, adjustments, orders in Phase 4) -----------------


def receive(
    level: StockLevel, quantity: Decimal, ref: Ref, *, by: User | None, unit_cost: Decimal | None
) -> StockMovement:
    return _apply_movement(level, MovementType.INWARD, quantity, ref, by=by, unit_cost=unit_cost)


def add(
    level: StockLevel, quantity: Decimal, ref: Ref, *, by: User | None, reason: str = ""
) -> StockMovement:
    return _apply_movement(level, MovementType.ADJUSTMENT_IN, quantity, ref, by=by, reason=reason)


def remove(
    level: StockLevel,
    quantity: Decimal,
    ref: Ref,
    *,
    by: User | None,
    reason: str = "",
    movement_type: str = MovementType.ADJUSTMENT_OUT,
) -> StockMovement:
    """Take stock out (adjustment or damage). Never touches reserved stock (PLAN S4)."""
    if MOVEMENT_KINDS[movement_type] != Direction(-1, 0):
        raise ValueError(f"{movement_type} does not remove unreserved stock")
    return _apply_movement(level, movement_type, quantity, ref, by=by, reason=reason)


def reserve(level: StockLevel, quantity: Decimal, ref: Ref, *, by: User | None) -> StockMovement:
    return _apply_movement(level, MovementType.RESERVE, quantity, ref, by=by)


def release(level: StockLevel, quantity: Decimal, ref: Ref, *, by: User | None) -> StockMovement:
    return _apply_movement(level, MovementType.RELEASE, quantity, ref, by=by)


def consume_reserved(
    level: StockLevel, quantity: Decimal, ref: Ref, *, by: User | None
) -> StockMovement:
    return _apply_movement(level, MovementType.SALE, quantity, ref, by=by)


# --- Cost method (ADR-041) ---------------------------------------------------------------------


class CostMethod:
    WEIGHTED_AVERAGE = "WEIGHTED_AVERAGE"
    LAST_PURCHASE = "LAST_PURCHASE"
    MANUAL = "MANUAL"


def apply_cost_method(
    product_id: UUID,
    *,
    on_hand_before: Decimal,
    received: Decimal,
    unit_cost: Decimal,
    source: str,
) -> Decimal | None:
    """Update the product's cost price from a receipt per ⚙ ``stock.cost_method``.

    Call with the product's stock level locked, so ``on_hand_before`` is current. Returns the new
    cost price, or ``None`` when the method is MANUAL. Automatic changes are audited with the
    receipt number. (With several warehouses, ``on_hand_before`` must become the product total.)
    """
    method = get_setting("stock.cost_method", require_tenant_id())
    if method == CostMethod.MANUAL:
        return None
    product = Product.objects.select_for_update().get(pk=product_id)
    if method == CostMethod.LAST_PURCHASE:
        new_cost = round2(unit_cost)
    else:
        new_cost = weighted_average_cost(on_hand_before, product.cost_price, received, unit_cost)
    old_cost = product.cost_price
    if old_cost != new_cost:
        product.cost_price = new_cost
        product.save(update_fields=["cost_price", "updated_at"])
        audit.record(
            "catalog.product_price_changed",
            target=product,
            target_repr=f"{product.code} {product.name}",
            changes=audit.diff({"cost_price": old_cost}, {"cost_price": new_cost}),
            metadata={"updated_by": source, "cost_method": method},
        )
    return new_cost


# --- Warehouse details (PLAN §3.7) ---------------------------------------------------------------

WAREHOUSE_FIELDS = ("name", "address_line1", "address_line2", "city", "pincode", "state_id")


@transaction.atomic
def update_warehouse(warehouse_id: UUID, changes: dict[str, Any], *, by: User) -> Warehouse:
    """Rename a warehouse or change its address (``settings.manage``, audited)."""
    from apps.platform.models import State

    warehouse: Warehouse | None = (
        Warehouse.objects.select_for_update().filter(pk=warehouse_id).first()
    )
    if warehouse is None:
        raise NotFound()
    before = audit.snapshot(warehouse, WAREHOUSE_FIELDS)
    for key in WAREHOUSE_FIELDS:
        if key in changes:
            value = changes[key]
            setattr(warehouse, key, value.strip() if isinstance(value, str) else value)
    errors: dict[str, list[str]] = {}
    if not warehouse.name:
        errors["name"] = ["Enter a name."]
    if warehouse.pincode and not (warehouse.pincode.isdigit() and len(warehouse.pincode) == 6):
        errors["pincode"] = ["Enter a 6-digit PIN code."]
    if warehouse.state_id and not State.objects.filter(pk=warehouse.state_id).exists():
        errors["state"] = ["Choose a state."]
    if errors:
        raise InvalidFields(errors)
    diff = audit.diff(before, audit.snapshot(warehouse, WAREHOUSE_FIELDS))
    if diff:
        warehouse.save()
        audit.record(
            "stock.warehouse_updated", target=warehouse, target_repr=warehouse.name, changes=diff
        )
    return warehouse
