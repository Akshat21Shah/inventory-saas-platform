"""Receiving against a purchase order (ADR-053 item 6).

- "Receive" makes a goods-receipt draft with what is still due and the order's costs, so staff who
  can't see costs receive with nothing left "cost pending". One draft per order at a time.
- Posting it adds to each line's received quantity and moves the order to Partly received or
  Received. More than ordered is accepted up to ⚙ ``purchasing.over_receipt_tolerance_percent``
  (10%) over the order; beyond it, someone with ``purchasing.manage`` must confirm (audited).
- Any posted receipt with a supplier records the supplier's last cost per product.

Lock order when posting: the receipt (``inventory.receipts``), then the purchase order (here),
then the stock rows; purchase-order services lock only the order.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import F

from apps.accounts.models import User
from apps.audit import services as audit
from apps.billing.tax import stock_value
from apps.inventory.models import StockInward, StockInwardLine
from apps.platform.selectors import get_setting
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, SupplierProduct
from apps.purchasing.orders import OPEN, NotEditable, lock
from common.error_codes import ErrorCode
from common.errors import DomainError
from common.tenancy import require_tenant_id

S = PurchaseOrder.Status
UNIT_COST_STEP = Decimal("0.0001")


class OverReceipt(DomainError):
    status_code = 409
    code = ErrorCode.OVER_RECEIPT
    default_message = "More is being received than was ordered."


def open_draft(order_id: UUID) -> StockInward | None:
    found: StockInward | None = StockInward.objects.filter(
        purchase_order_id=order_id, status=StockInward.Status.DRAFT
    ).first()
    return found


def receive_order(order_id: UUID, *, by: User) -> StockInward:
    """The goods-receipt draft for what is still due (the open one, if there is already one)."""
    order = lock(order_id)
    if order.status not in OPEN:
        raise NotEditable("Only a sent or partly received order can be received.")
    existing = open_draft(order.pk)
    if existing is not None:
        return existing
    due = [line for line in order.lines.select_related("product") if line.due > 0]
    if not due:
        raise NotEditable("Nothing is still due on this order.")
    inward = StockInward(
        warehouse=order.warehouse,
        supplier=order.supplier,
        supplier_name=order.supplier.name,
        purchase_order=order,
        created_by=by,
    )
    inward.save()
    rows = []
    for index, line in enumerate(due, start=1):
        pack = line.product.pack_size
        whole_packs = line.entered_unit == "PACK" and pack and line.due % pack == 0
        factor = pack if whole_packs and pack else Decimal("1")
        entered_qty = line.due / factor
        entered_cost = (
            None if line.unit_cost is None else (line.unit_cost * factor).quantize(UNIT_COST_STEP)
        )
        rows.append(
            StockInwardLine(
                tenant_id=inward.tenant_id,  # bulk_create skips TenantScopedModel.save
                inward=inward,
                line_no=index,
                product_id=line.product_id,
                purchase_order_line=line,
                entered_unit="PACK" if whole_packs else "BASE",
                entered_qty=entered_qty,
                quantity=line.due,
                entered_cost=entered_cost,
                unit_cost=line.unit_cost,
                line_cost=None if entered_cost is None else stock_value(entered_qty, entered_cost),
                created_by=by,
            )
        )
    StockInwardLine.objects.bulk_create(rows)
    costs = [row.line_cost for row in rows if row.line_cost is not None]
    inward.total_cost = sum(costs, Decimal("0.00")) if costs else None
    inward.save(update_fields=["total_cost", "updated_at"])
    return inward


def _tolerance() -> int:
    return int(get_setting("purchasing.over_receipt_tolerance_percent", require_tenant_id()))


def over_order(order: PurchaseOrder, receiving: dict[UUID, Decimal]) -> list[dict[str, Any]]:
    """Order lines this receipt takes over the ordered quantity, with how far."""
    tolerance = _tolerance()
    found = []
    for line in order.lines.all():
        coming = receiving.get(line.pk)
        if not coming:
            continue
        ordered = line.quantity - line.qty_cancelled
        total = line.qty_received + coming
        if total > ordered:
            limit = ordered * (100 + tolerance) / 100
            found.append(
                {
                    "line_id": str(line.pk),
                    "product_code": line.product_code,
                    "ordered": f"{ordered:.3f}",
                    "received_before": f"{line.qty_received:.3f}",
                    "receiving": f"{coming:.3f}",
                    "beyond_tolerance": total > limit,
                }
            )
    return found


def before_post(
    inward: StockInward, lines: list[StockInwardLine], *, by: User, confirm: bool
) -> PurchaseOrder:
    """Lock the order and check the quantities; raise ``OverReceipt`` beyond the tolerance unless
    someone who manages purchasing confirms."""
    order: PurchaseOrder = PurchaseOrder.objects.select_for_update().get(
        pk=inward.purchase_order_id
    )
    if order.status not in OPEN:
        raise NotEditable(
            f"{order.number} is {order.get_status_display().lower()}: nothing more can be "
            "received against it. Delete this draft and receive without the order."
        )
    receiving: dict[UUID, Decimal] = defaultdict(Decimal)
    for line in lines:
        if line.purchase_order_line_id:
            receiving[line.purchase_order_line_id] += line.quantity
    over = over_order(order, receiving)
    beyond = [row for row in over if row["beyond_tolerance"]]
    if not beyond:
        return order
    allowed = by.has_permission_code("purchasing.manage")
    if not confirm or not allowed:
        raise OverReceipt(
            "Someone who manages purchasing must confirm receiving this much." if confirm else None,
            details={"lines": over, "tolerance_percent": _tolerance(), "can_confirm": allowed},
        )
    audit.record(
        "purchasing.over_receipt_confirmed",
        target=order,
        target_repr=order.number,
        metadata={"receipt_id": str(inward.pk), "lines": beyond},
    )
    return order


def after_post(order: PurchaseOrder, lines: list[StockInwardLine]) -> None:
    """Add what arrived to the order's lines and move the order on."""
    for line in lines:
        if line.purchase_order_line_id:
            PurchaseOrderLine.objects.filter(pk=line.purchase_order_line_id).update(
                qty_received=F("qty_received") + line.quantity
            )
    still_due = any(line.due > 0 for line in order.lines.all())
    order.status = S.PARTLY_RECEIVED if still_due else S.RECEIVED
    order.save(update_fields=["status", "updated_at"])


def record_costs(inward: StockInward, lines: list[StockInwardLine], *, by: User) -> None:
    """The supplier's last cost per product, from a posted receipt (the link is made if the
    product wasn't linked to this supplier yet; never made preferred automatically)."""
    if inward.supplier_id is None:
        return
    for line in lines:
        if line.unit_cost is None:
            continue
        updated = SupplierProduct.objects.filter(
            supplier_id=inward.supplier_id, product_id=line.product_id
        ).update(last_unit_cost=line.unit_cost)
        if not updated:
            SupplierProduct.objects.create(
                supplier_id=inward.supplier_id,
                product_id=line.product_id,
                last_unit_cost=line.unit_cost,
                created_by=by,
            )
