"""Stock adjustments and reorder levels (spec 5.7, ADR-041 items 10 and 11). Write logic only.

An adjustment covers several products with one reason code and a required note. Each line adds,
removes, or records a counted quantity (the server works out the difference). Reserved stock is
never removed (``STOCK_RESERVED``). Adjustments are immutable and audited.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction

from apps.accounts.models import User
from apps.audit import services as audit
from apps.catalog.models import Product
from apps.inventory import alerts, services
from apps.inventory.models import (
    AdjustmentReason,
    MovementType,
    ReferenceType,
    StockAdjustment,
    StockAdjustmentLine,
)
from apps.inventory.services import InsufficientStock, StockReserved
from common.dates import today_ist
from common.db import retry_on_deadlock
from common.errors import InvalidFields, NotFound
from common.sequences import next_value

MAX_LINES = 500
QTY_STEP = Decimal("0.001")
Mode = StockAdjustmentLine.Mode


@dataclass(frozen=True)
class AdjustmentLineInput:
    product_id: UUID
    mode: str
    quantity: Decimal  # the counted quantity for COUNTED; otherwise how much to add or remove
    # Cost per base unit before GST for stock that comes in (opening stock import); needs
    # pricing.manage, and runs the cost method (ADR-041).
    unit_cost: Decimal | None = None


@dataclass(frozen=True)
class AdjustmentInput:
    reason_code: str
    note: str
    lines: Sequence[AdjustmentLineInput]


@dataclass(frozen=True)
class AdjustmentResult:
    adjustment: StockAdjustment
    unchanged: list[str]  # product codes whose count matched the stock (no line written)


def _validate(data: AdjustmentInput, by: User) -> dict[UUID, Product]:
    errors: dict[str, list[str]] = {}
    if any(line.unit_cost is not None for line in data.lines) and not by.has_permission_code(
        "pricing.manage"
    ):
        errors["lines"] = ["Only staff who manage pricing can enter costs."]
    if data.reason_code not in AdjustmentReason.values:
        errors["reason_code"] = ["Choose a reason."]
    if not data.note.strip():
        errors["note"] = ["Write a short note about why the stock changes."]
    if not data.lines:
        errors["lines"] = ["Add at least one product."]
    elif len(data.lines) > MAX_LINES:
        errors["lines"] = [f"An adjustment can have up to {MAX_LINES} lines."]
    if errors:
        raise InvalidFields(errors)
    products = {
        p.pk: p
        for p in Product.objects.filter(
            pk__in={line.product_id for line in data.lines}, deleted_at__isnull=True
        ).select_related("unit")
    }
    seen: set[UUID] = set()
    for index, line in enumerate(data.lines, start=1):
        product = products.get(line.product_id)
        problem = None
        if product is None:
            problem = "Choose an existing product."
        elif line.product_id in seen:
            problem = f"{product.code} is already on this adjustment."
        elif line.mode not in Mode.values:
            problem = "Choose add, remove or counted."
        elif line.quantity < 0 or (line.mode != Mode.COUNTED and line.quantity == 0):
            problem = (
                "Enter the counted quantity (0 or more)."
                if line.mode == Mode.COUNTED
                else "Enter a quantity above 0."
            )
        elif line.quantity != line.quantity.quantize(QTY_STEP):
            problem = "Enter a quantity with at most 3 decimals."
        elif not product.unit.allows_decimal and line.quantity % 1:
            problem = f"{product.unit.code} is counted in whole numbers."
        elif line.unit_cost is not None and line.unit_cost < 0:
            problem = "Enter a cost of 0 or more."
        if problem:
            errors[f"lines.{index}"] = [problem]
        seen.add(line.product_id)
    if errors:
        raise InvalidFields(errors)
    return products


@retry_on_deadlock()
def create_adjustment(data: AdjustmentInput, *, by: User) -> AdjustmentResult:
    products = _validate(data, by)
    note = data.note.strip()
    with transaction.atomic():
        warehouse = services.default_warehouse()
        levels = services.lock_levels([line.product_id for line in data.lines], warehouse)
        year = today_ist().year
        number = f"ADJ-{year}-{next_value('ADJ', str(year)):05d}"
        adjustment = StockAdjustment.objects.create(
            number=number,
            warehouse=warehouse,
            reason_code=data.reason_code,
            note=note,
            created_by=by,
        )
        ref = services.Ref(ReferenceType.ADJUSTMENT, adjustment.pk, number)
        out_type = (
            MovementType.DAMAGE
            if data.reason_code == AdjustmentReason.DAMAGE
            else MovementType.ADJUSTMENT_OUT
        )
        indexed = sorted(enumerate(data.lines, start=1), key=lambda pair: pair[1].product_id)
        rows: list[StockAdjustmentLine] = []
        unchanged: list[str] = []
        logged: list[dict[str, Any]] = []
        for index, line in indexed:
            product = products[line.product_id]
            level = levels[line.product_id]
            before = level.quantity_on_hand
            change = {
                Mode.ADD: line.quantity,
                Mode.REMOVE: -line.quantity,
                Mode.COUNTED: line.quantity - before,
            }[Mode(line.mode)]
            if change == 0:
                unchanged.append(product.code)
                continue
            try:
                if change > 0:
                    services.add(level, change, ref, by=by, reason=note, unit_cost=line.unit_cost)
                    if line.unit_cost is not None:
                        services.apply_cost_method(
                            product.pk,
                            on_hand_before=before,
                            received=change,
                            unit_cost=line.unit_cost,
                            source=number,
                        )
                else:
                    services.remove(level, -change, ref, by=by, reason=note, movement_type=out_type)
            except (StockReserved, InsufficientStock) as exc:
                available = before - level.quantity_reserved
                raise type(exc)(
                    f"{product.code}: only {available.normalize():f} can be removed "
                    "(the rest is reserved for orders or not in stock).",
                    details={"line": index, "product_code": product.code, **exc.details},
                ) from exc
            rows.append(
                StockAdjustmentLine(
                    tenant_id=adjustment.tenant_id,  # bulk_create skips TenantScopedModel.save
                    adjustment=adjustment,
                    line_no=index,
                    product=product,
                    mode=line.mode,
                    entered_qty=line.quantity,
                    quantity_change=change,
                    on_hand_before=before,
                    created_by=by,
                )
            )
            logged.append({"product": product.code, "before": before, "change": change})
        if not rows:
            raise InvalidFields({"lines": ["Nothing changes: every count matches the stock."]})
        StockAdjustmentLine.objects.bulk_create(sorted(rows, key=lambda row: row.line_no))
        audit.record(
            "stock.adjusted",
            target=adjustment,
            target_repr=number,
            metadata={
                "reason": data.reason_code,
                "note": note,
                "lines": logged,
                "unchanged": unchanged,
            },
        )
    return AdjustmentResult(adjustment, unchanged)


# --- Reorder level (ADR-041 item 10) -------------------------------------------------------------


@retry_on_deadlock()
def set_reorder_level(product_id: UUID, reorder_level: Decimal, *, by: User) -> Product:
    """Change a product's reorder level (audited) and re-check its alerts."""
    with transaction.atomic():
        product: Product | None = (
            Product.objects.filter(pk=product_id, deleted_at__isnull=True)
            .select_related("unit")
            .first()
        )
        if product is None:
            raise NotFound()
        if reorder_level < 0 or reorder_level != reorder_level.quantize(QTY_STEP):
            raise InvalidFields({"reorder_level": ["Enter 0 or more, with at most 3 decimals."]})
        if not product.unit.allows_decimal and reorder_level % 1:
            raise InvalidFields(
                {"reorder_level": [f"{product.unit.code} is counted in whole numbers."]}
            )
        reorder_level = reorder_level.quantize(QTY_STEP)
        # Stock level first (L3), then the product row, as receipts do.
        levels = services.lock_levels([product.pk], services.default_warehouse())
        product = Product.objects.select_for_update().get(pk=product.pk)
        old = product.reorder_level
        if old == reorder_level:
            return product
        product.reorder_level = reorder_level
        product.save(update_fields=["reorder_level", "updated_at"])
        audit.record(
            "stock.reorder_level_changed",
            target=product,
            target_repr=f"{product.code} {product.name}",
            changes=audit.diff({"reorder_level": old}, {"reorder_level": reorder_level}),
        )
        for level in levels.values():
            alerts.evaluate(level, reorder_level)
    return product
