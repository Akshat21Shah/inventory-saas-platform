"""Goods receipts (GRN): draft → posted, pack entry, costs before GST, cost pending and complete
costs (spec 5.7, PLAN §5.2 "stock inward", ADR-041). Write logic only; reads are in selectors."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.models import User
from apps.audit import services as audit
from apps.billing.tax import cost_per_base_unit, stock_value
from apps.catalog.models import Product
from apps.inventory import services
from apps.inventory.models import ReferenceType, StockInward, StockInwardLine
from common.dates import today_ist
from common.db import retry_on_deadlock
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields, NotFound
from common.sequences import next_value

MAX_LINES = 500
COST_VIEW = "costs.view"  # ADR-042
COST_MANAGE = "costs.manage"
QTY_STEP = Decimal("0.001")


class NotDraft(DomainError):
    status_code = 409
    code = ErrorCode.INVALID_STATE_TRANSITION
    default_message = gettext_lazy("This goods receipt has been posted and can't be changed.")


class NoPendingCosts(DomainError):
    status_code = 409
    code = ErrorCode.INVALID_STATE_TRANSITION
    default_message = gettext_lazy("This goods receipt has no lines waiting for a cost.")


@dataclass(frozen=True)
class LineInput:
    product_id: UUID
    entered_qty: Decimal
    entered_unit: str = StockInwardLine.EnteredUnit.BASE
    entered_cost: Decimal | None = None  # per entered unit, before GST
    id: UUID | None = None  # an existing draft line (keeps its cost for staff who can't see it)


@dataclass(frozen=True)
class ReceiptInput:
    lines: Sequence[LineInput]
    supplier_name: str = ""
    supplier_ref: str = ""
    bill_number: str = ""
    bill_date: date | None = None
    supplier_id: UUID | None = None  # flag purchasing (ADR-053); its name unless one is typed
    notes: str = ""


def _can_see_costs(by: User) -> bool:
    return bool(by.has_permission_code(COST_VIEW))


def _lines(
    data: ReceiptInput, by: User, existing: Mapping[UUID, StockInwardLine]
) -> list[StockInwardLine]:
    """Validate the lines and build unsaved rows (base quantities and costs worked out)."""
    errors: dict[str, list[str]] = {}
    if not data.lines:
        errors["lines"] = [_("Add at least one product.")]
    elif len(data.lines) > MAX_LINES:
        errors["lines"] = [
            _("A goods receipt can have up to %(max_lines)s lines.") % {"max_lines": MAX_LINES}
        ]
    sees_costs = _can_see_costs(by)
    if not sees_costs and any(line.entered_cost is not None for line in data.lines):
        errors["lines"] = [_("Only staff who can see costs can enter them.")]
    if errors:
        raise InvalidFields(errors)
    products = {
        p.pk: p
        for p in Product.objects.filter(
            pk__in={line.product_id for line in data.lines}, deleted_at__isnull=True
        ).select_related("unit", "pack_unit")
    }
    rows: list[StockInwardLine] = []
    for index, line in enumerate(data.lines, start=1):
        key = f"lines.{index}"
        product = products.get(line.product_id)
        if product is None:
            errors[key] = [_("Choose an existing product.")]
            continue
        problem = _quantity_problem(product, line)
        if problem:
            errors[key] = [problem]
            continue
        entered_cost = line.entered_cost
        if not sees_costs and line.id is not None and line.id in existing:
            entered_cost = existing[line.id].entered_cost  # kept, never shown to this user
        if entered_cost is not None and entered_cost < 0:
            errors[key] = [_("Enter a cost of 0 or more.")]
            continue
        factor = product.pack_size if line.entered_unit == "PACK" else Decimal("1")
        old = existing.get(line.id) if line.id is not None else None
        rows.append(
            StockInwardLine(
                line_no=index,
                product=product,
                # A line from a purchase order stays linked to it (same product).
                purchase_order_line_id=(
                    old.purchase_order_line_id
                    if old is not None and old.product_id == product.pk
                    else None
                ),
                entered_unit=line.entered_unit,
                entered_qty=line.entered_qty,
                quantity=(line.entered_qty * factor).quantize(QTY_STEP),
                entered_cost=entered_cost,
                unit_cost=None
                if entered_cost is None
                else cost_per_base_unit(entered_cost, factor),
                line_cost=None
                if entered_cost is None
                else stock_value(line.entered_qty, entered_cost),
                created_by=by,
            )
        )
    if errors:
        raise InvalidFields(errors)
    return rows


def _quantity_problem(product: Product, line: LineInput) -> str | None:
    if line.entered_unit not in StockInwardLine.EnteredUnit.values:
        return _("Choose the unit or the pack.")
    if line.entered_unit == "PACK" and product.pack_unit_id is None:
        return _("%(code)s has no pack size. Enter the quantity in %(code2)s.") % {
            "code": product.code,
            "code2": product.unit.code,
        }
    unit = product.pack_unit if line.entered_unit == "PACK" else product.unit
    if line.entered_qty <= 0:
        return _("Enter a quantity above 0.")
    if line.entered_qty != line.entered_qty.quantize(QTY_STEP):
        return _("Enter a quantity with at most 3 decimals.")
    if unit is not None and not unit.allows_decimal and line.entered_qty % 1:
        return _("%(code)s is counted in whole numbers.") % {"code": unit.code}
    return None


def _supplier(supplier_id: UUID) -> Any:
    from apps.platform.selectors import is_feature_enabled
    from apps.purchasing.models import Supplier

    if not is_feature_enabled("purchasing"):
        raise InvalidFields({"supplier_id": [_("Purchasing isn't switched on for your business.")]})
    found = Supplier.objects.filter(pk=supplier_id, deleted_at__isnull=True, is_active=True).first()
    if found is None:
        raise InvalidFields({"supplier_id": [_("Choose one of your active suppliers.")]})
    return found


def _header(inward: StockInward, data: ReceiptInput) -> None:
    inward.supplier_name = data.supplier_name.strip()[:200]
    if inward.purchase_order_id is not None and inward.supplier is not None:
        # The order's supplier, whatever is sent.
        inward.supplier_name = inward.supplier_name or inward.supplier.name[:200]
    else:
        inward.supplier = None
        if data.supplier_id is not None:
            inward.supplier = _supplier(data.supplier_id)
            inward.supplier_name = inward.supplier_name or inward.supplier.name[:200]
    inward.supplier_ref = data.supplier_ref.strip()[:60]
    inward.bill_number = data.bill_number.strip()[:60]
    inward.bill_date = data.bill_date
    inward.notes = data.notes.strip()
    if data.bill_date is not None and data.bill_date > today_ist():
        raise InvalidFields({"bill_date": [_("The bill date can't be in the future.")]})


def _save_lines(inward: StockInward, rows: list[StockInwardLine]) -> None:
    inward.lines.all().delete()
    for row in rows:
        row.inward = inward
        row.tenant_id = inward.tenant_id  # bulk_create skips TenantScopedModel.save
    StockInwardLine.objects.bulk_create(rows)


def _set_totals(inward: StockInward, lines: Sequence[StockInwardLine]) -> None:
    costs = [line.line_cost for line in lines if line.line_cost is not None]
    inward.total_cost = sum(costs, Decimal("0.00")) if costs else None


# --- Drafts --------------------------------------------------------------------------------------


@transaction.atomic
def create_draft(data: ReceiptInput, *, by: User) -> StockInward:
    rows = _lines(data, by, {})
    inward = StockInward(warehouse=services.default_warehouse(), created_by=by)
    _header(inward, data)
    _set_totals(inward, rows)
    inward.save()
    _save_lines(inward, rows)
    return inward


def _locked_draft(inward_id: UUID) -> StockInward:
    inward: StockInward | None = (
        StockInward.objects.select_for_update().filter(pk=inward_id).first()
    )
    if inward is None:
        raise NotFound()
    if inward.status != StockInward.Status.DRAFT:
        raise NotDraft()
    return inward


@transaction.atomic
def update_draft(inward_id: UUID, data: ReceiptInput, *, by: User) -> StockInward:
    inward = _locked_draft(inward_id)
    existing = {line.pk: line for line in inward.lines.all()}
    rows = _lines(data, by, existing)
    _header(inward, data)
    _set_totals(inward, rows)
    inward.save()
    _save_lines(inward, rows)
    return inward


@transaction.atomic
def delete_draft(inward_id: UUID, *, by: User) -> None:
    _locked_draft(inward_id).delete()


# --- Posting -------------------------------------------------------------------------------------


@retry_on_deadlock()
def post(inward_id: UUID, *, by: User, confirm_over_receipt: bool = False) -> StockInward:
    """Post a draft: stock up, one movement per line, the cost method for lines with a cost, and
    "cost pending" for lines without one. Idempotency is handled by the API (Idempotency-Key).
    A draft from a purchase order also updates the order (``apps.purchasing.receiving``)."""
    with transaction.atomic():
        inward = _locked_draft(inward_id)
        lines = sorted(inward.lines.all(), key=lambda row: (row.product_id, row.line_no))
        if not lines:
            raise InvalidFields({"lines": [_("Add at least one product.")]})
        from apps.purchasing import receiving

        order = None
        if inward.purchase_order_id is not None:
            order = receiving.before_post(inward, lines, by=by, confirm=confirm_over_receipt)
        inactive = Product.objects.filter(
            pk__in={line.product_id for line in lines}, deleted_at__isnull=False
        ).values_list("code", flat=True)
        if inactive:
            raise InvalidFields(
                {
                    "lines": [
                        _("Deleted products can't be received: %(inactive)s.")
                        % {"inactive": ", ".join(sorted(inactive))}
                    ]
                }
            )
        # Lock order: shops and orders waiting for these products (L1, L2), stock levels (L3),
        # then the GRN sequence, then product rows for the cost price. Only postings take the GRN
        # sequence, and they always hold their levels first.
        product_ids = [line.product_id for line in lines]
        waiting = services.hold_waiting_orders(product_ids)
        levels = services.lock_levels(product_ids, inward.warehouse)
        year = today_ist().year
        number = f"GRN-{year}-{next_value('GRN', str(year)):05d}"
        ref = services.Ref(ReferenceType.INWARD, inward.pk, number)
        pending = 0
        for line in lines:
            level = levels[line.product_id]
            on_hand_before = level.quantity_on_hand
            services.receive(level, line.quantity, ref, by=by, unit_cost=line.unit_cost)
            if line.unit_cost is None:
                line.cost_status = StockInwardLine.CostStatus.PENDING
                pending += 1
            else:
                line.cost_status = StockInwardLine.CostStatus.SET
                services.apply_cost_method(
                    line.product_id,
                    on_hand_before=on_hand_before,
                    received=line.quantity,
                    unit_cost=line.unit_cost,
                    source=number,
                )
            line.save(update_fields=["cost_status", "updated_at"])  # the receipt is still a draft
        inward.status = StockInward.Status.POSTED
        inward.number = number
        inward.posted_at = timezone.now()
        inward.posted_by = by
        inward.cost_pending_lines = pending
        inward.save()
        services.serve_backorders(levels, waiting, trigger="INWARD", source_id=inward.pk, by=by)
        if order is not None:
            receiving.after_post(order, lines)
        receiving.record_costs(inward, lines, by=by)
        audit.record(
            "stock.inward_posted",
            target=inward,
            target_repr=number,
            metadata={"lines": len(lines), "cost_pending_lines": pending},
        )
    return inward


def create_and_post(data: ReceiptInput, *, by: User) -> StockInward:
    """One step for phones: save and post. Both run in one transaction, so a failed post leaves
    nothing behind."""

    @retry_on_deadlock()
    def run() -> StockInward:
        with transaction.atomic():
            draft = create_draft(data, by=by)
            return post(draft.pk, by=by)

    return run()


# --- Complete costs (ADR-041 item 8) -------------------------------------------------------------


@retry_on_deadlock()
def complete_costs(inward_id: UUID, costs: Mapping[UUID, Decimal], *, by: User) -> StockInward:
    """Add costs (per entered unit, before GST) to cost-pending lines of a posted receipt. Changes
    nothing else. The cost method runs now, with the stock and cost price of this moment."""
    if not by.has_permission_code(COST_MANAGE):
        raise InvalidFields({"costs": [_("Only staff who manage costs can complete them.")]})
    with transaction.atomic():
        inward: StockInward | None = (
            StockInward.objects.select_for_update().filter(pk=inward_id).first()
        )
        if inward is None:
            raise NotFound()
        if inward.status != StockInward.Status.POSTED or inward.cost_pending_lines == 0:
            raise NoPendingCosts()
        pending = {
            line.pk: line
            for line in inward.lines.filter(
                cost_status=StockInwardLine.CostStatus.PENDING
            ).select_related("product")
        }
        errors = _cost_errors(costs, pending)
        if errors:
            raise InvalidFields(errors)
        chosen = sorted(
            (pending[line_id] for line_id in costs), key=lambda row: (row.product_id, row.pk)
        )
        levels = services.lock_levels([line.product_id for line in chosen], inward.warehouse)
        now = timezone.now()
        applied: list[dict[str, Any]] = []
        for line in chosen:
            factor = line.product.pack_size if line.entered_unit == "PACK" else Decimal("1")
            line.entered_cost = costs[line.pk]
            line.unit_cost = cost_per_base_unit(line.entered_cost, factor)
            line.line_cost = stock_value(line.entered_qty, line.entered_cost)
            line.cost_status = StockInwardLine.CostStatus.SET
            line.cost_completed_at, line.cost_completed_by = now, by
            line.save()
            # The received goods are already in stock: the "stock before" for the average is
            # what is on hand now minus this line (never below zero).
            on_hand_now = levels[line.product_id].quantity_on_hand
            services.apply_cost_method(
                line.product_id,
                on_hand_before=max(on_hand_now - line.quantity, Decimal("0")),
                received=line.quantity,
                unit_cost=line.unit_cost,
                source=str(inward.number),
            )
            applied.append(
                {"line": line.line_no, "product": line.product.code, "cost": line.entered_cost}
            )
        inward.cost_pending_lines -= len(chosen)
        _set_totals(inward, list(inward.lines.all()))
        inward.save(update_fields=["cost_pending_lines", "total_cost", "updated_at"])
        audit.record(
            "stock.inward_costs_completed",
            target=inward,
            target_repr=str(inward.number),
            metadata={"lines": applied, "still_pending": inward.cost_pending_lines},
        )
    return inward


def _cost_errors(
    costs: Mapping[UUID, Decimal], pending: Mapping[UUID, StockInwardLine]
) -> dict[str, list[str]]:
    if not costs:
        return {"costs": [_("Enter at least one cost.")]}
    errors: dict[str, list[str]] = {}
    for line_id, cost in costs.items():
        if line_id not in pending:
            errors[str(line_id)] = [_("This line isn't waiting for a cost.")]
        elif cost is None or cost < 0:
            errors[str(line_id)] = [_("Enter a cost of 0 or more.")]
    return errors
