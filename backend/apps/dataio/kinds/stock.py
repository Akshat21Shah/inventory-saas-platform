"""Opening stock import (PLAN task 3.7, ADR-041): product code, quantity and an optional cost per
unit before GST. Two modes, chosen for every import: "Add to stock" adds the quantity; "Set stock
to this count" makes the stock equal to it. The file becomes ONE adjustment with the reason
"Opening stock" and one line per changed row (ADR-042), with movements, a number and an audit
entry like any adjustment. If the stock changed since validation so that a row can't be applied,
nothing from the file is applied.
"""

from collections.abc import Iterable
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models.functions import Lower

from apps.accounts.models import User
from apps.catalog import selectors as catalog
from apps.dataio.kinds.base import Column, RowPlan
from apps.dataio.parsing import Sheet, parse_decimal
from apps.inventory import adjustments
from apps.inventory.models import AdjustmentReason
from apps.inventory.selectors import with_stock
from apps.platform.selectors import get_setting
from common.tenancy import require_tenant_id

C = Column
STOCK_ADD, STOCK_SET = "STOCK_ADD", "STOCK_SET"
NOTE = "Opening stock import"
MAX_ROWS = 20_000  # one document per file; the upload size limit is reached first

COLUMNS: tuple[Column, ...] = (
    C("product_code", "Product code", ("code", "item code", "sku"), True, "", "PG-100"),
    C(
        "quantity",
        "Quantity",
        ("qty", "stock", "count", "closing stock", "opening stock", "quantity in stock"),
        True,
        "In the product's unit (not packs).",
        "120",
    ),
    C(
        "cost",
        "Cost per unit (before GST)",
        ("cost", "cost price", "purchase price", "purchase rate"),
        False,
        "Optional. Updates the cost price the way your cost setting says.",
        "7.50",
    ),
    C("product_name", "Product name", (), False, "For reference; not imported.", "Parle-G 100g"),
)
LABEL = {c.name: c.label for c in COLUMNS}


def _number(value: Decimal) -> str:
    return f"{value.normalize():f}"


class OpeningStockKind:
    code = "OPENING_STOCK"
    label = "Opening stock"
    permission = "stock.adjust"
    key_label = LABEL["product_code"]
    columns = COLUMNS
    modes = (STOCK_ADD, STOCK_SET)
    restricted = {"cost": "costs.view"}  # importing a cost needs costs.manage (ADR-042)

    def reference_lists(self) -> dict[str, list[str]]:
        return {}

    def plan(self, sheet: Sheet, mode: str, by: User) -> list[RowPlan]:
        codes = {r.values.get("product_code", "").strip().lower() for r in sheet.rows} - {""}
        products = {
            p.code.lower(): p
            for p in with_stock(catalog.products()).annotate(lc=Lower("code")).filter(lc__in=codes)
        }
        can_cost = by.has_permission_code("costs.manage")
        manual = get_setting("stock.cost_method", require_tenant_id()) == "MANUAL"
        seen: dict[UUID, int] = {}
        plans: list[RowPlan] = []
        for row in sheet.rows:
            v = row.values
            plan = RowPlan(number=row.number, key=v.get("product_code", ""))
            plans.append(plan)
            product = products.get(v.get("product_code", "").strip().lower())
            if not v.get("product_code"):
                plan.error(LABEL["product_code"], "Enter the product code.")
            elif product is None:
                plan.error(LABEL["product_code"], f"No product has the code {v['product_code']}.")
            quantity = self._quantity(plan, v.get("quantity", ""), mode)
            cost = self._cost(plan, v.get("cost", ""), can_cost)
            if product is None or quantity is None or not plan.ok:
                continue
            if product.pk in seen:
                plan.error(
                    LABEL["product_code"],
                    f"This product is also in row {seen[product.pk]}. List each product once.",
                )
                continue
            seen[product.pk] = row.number
            plan.key = product.code
            if not product.unit.allows_decimal and quantity % 1:
                plan.error(LABEL["quantity"], f"{product.unit.code} is counted in whole numbers.")
                continue
            on_hand = Decimal(product.on_hand)  # type: ignore[attr-defined]
            reserved = Decimal(product.reserved)  # type: ignore[attr-defined]
            new = on_hand + quantity if mode == STOCK_ADD else quantity
            if new == on_hand:
                plan.action = "UNCHANGED"
                continue
            if new < reserved:
                plan.error(
                    LABEL["quantity"],
                    f"{_number(reserved)} {product.unit.code} is reserved for orders, so the "
                    "stock can't go below that.",
                )
                continue
            plan.action = "UPDATE"
            plan.target_id = product.pk
            plan.changes = {"Stock": [_number(on_hand), _number(new)]}
            if cost is not None:
                if new < on_hand:
                    plan.warnings.append("Stock goes down, so the cost is not used.")
                    cost = None
                elif manual:
                    plan.warnings.append(
                        "Your cost setting is “Never”, so the cost price won't change."
                    )
            plan.data = {
                "product_id": product.pk,
                "mode": "ADD" if mode == STOCK_ADD else "COUNTED",
                "quantity": quantity,
                "unit_cost": cost,
            }
        return plans

    def _quantity(self, plan: RowPlan, text: str, mode: str) -> Decimal | None:
        if not text:
            plan.error(LABEL["quantity"], "Enter the quantity.")
            return None
        try:
            value = parse_decimal(text, places=3)
        except ValueError:
            plan.error(LABEL["quantity"], f"{text} isn't a quantity (at most 3 decimals).")
            return None
        if value < 0 or (mode == STOCK_ADD and value == 0):
            plan.error(
                LABEL["quantity"],
                "Enter a quantity above 0." if mode == STOCK_ADD else "Can't be negative.",
            )
            return None
        return value

    def _cost(self, plan: RowPlan, text: str, can_cost: bool) -> Decimal | None:
        if not text:
            return None
        if not can_cost:
            plan.error(LABEL["cost"], "Only staff who manage costs can import costs.")
            return None
        try:
            value = parse_decimal(text, places=4)
        except ValueError:
            plan.error(LABEL["cost"], f"{text} isn't an amount (at most 4 decimals).")
            return None
        if value < 0:
            plan.error(LABEL["cost"], "Can't be negative.")
            return None
        return value

    def apply(self, row: RowPlan, *, by: User, cache: dict[str, Any]) -> None:
        self.apply_all([row], by=by, source="")

    def apply_all(self, rows: list[RowPlan], *, by: User, source: str) -> None:
        """The whole file as one adjustment (ADR-042)."""
        if not rows:
            return
        adjustments.create_adjustment(
            adjustments.AdjustmentInput(
                reason_code=AdjustmentReason.OPENING_STOCK,
                note=f"{NOTE}: {source}" if source else NOTE,
                lines=[
                    adjustments.AdjustmentLineInput(
                        r.data["product_id"],
                        r.data["mode"],
                        r.data["quantity"],
                        unit_cost=r.data["unit_cost"],
                    )
                    for r in rows
                ],
            ),
            by=by,
            max_lines=MAX_ROWS,
        )

    def export_rows(self) -> Iterable[dict[str, str]]:
        """Today's stock as a count sheet: edit the quantities and import with "Set stock"."""
        for p in with_stock(catalog.products()).order_by("code"):
            yield {
                "product_code": p.code,
                "quantity": _number(Decimal(p.on_hand)),  # type: ignore[attr-defined]
                "cost": "" if p.cost_price is None else f"{p.cost_price:.2f}",
                "product_name": p.name,
            }
