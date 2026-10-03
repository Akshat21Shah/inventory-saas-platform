"""Purchase orders (ADR-053 item 5). Every change is audited and prints the order again.

- Draft → Sent → Partly received → Received (receiving, 9a.6), or Closed (what is still due
  cancelled, with a reason) once something arrived, or Cancelled before anything did.
- A draft or a sent order is edited freely until something is received; a sent order that
  changed is sent again as the next revision ("Revised" on the copy).
- Costs are per base unit before GST. Staff without ``costs.view`` neither see nor enter them: a
  new line takes the supplier's last cost (else the product's cost price) and an existing line
  keeps its cost. GST is estimated from each product's rate, for information only; purchasing
  never touches the ledger.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy

from apps.accounts.models import User
from apps.audit import services as audit
from apps.billing.models import PdfStatus
from apps.billing.tax import cost_per_base_unit, round2, stock_value
from apps.catalog.models import Product
from apps.catalog.selectors import tax_rates_on
from apps.inventory import services as stock
from apps.platform.selectors import get_setting
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Supplier, SupplierProduct
from common.dates import today_ist
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields, NotFound
from common.numbers import fill
from common.outbox import emit
from common.sequences import next_value
from common.tenancy import require_tenant_id

MAX_LINES = 300
QTY_STEP = Decimal("0.001")
S = PurchaseOrder.Status
OPEN = (S.SENT, S.PARTLY_RECEIVED)  # waiting for goods


class NotEditable(DomainError):
    status_code = 409
    code = ErrorCode.INVALID_STATE_TRANSITION
    default_message = gettext_lazy("This purchase order can't be changed now.")


@dataclass(frozen=True)
class OrderLineInput:
    product_id: UUID
    entered_qty: Decimal
    entered_unit: str = "BASE"
    entered_cost: Decimal | None = None  # per entered unit, before GST; None: the usual cost
    id: UUID | None = None  # an existing line (keeps its cost for staff who can't see costs)


@dataclass(frozen=True)
class OrderInput:
    supplier_id: UUID
    lines: Sequence[OrderLineInput]
    expected_date: date | None = None
    notes: str = ""


def sees_costs(user: User) -> bool:
    return user.has_permission_code("costs.view")


def lead_days(supplier: Supplier) -> int:
    if supplier.lead_time_days:
        return supplier.lead_time_days
    return int(get_setting("planning.default_lead_days", require_tenant_id()))


def _supplier(supplier_id: UUID) -> Supplier:
    found: Supplier | None = Supplier.objects.filter(
        pk=supplier_id, deleted_at__isnull=True, is_active=True
    ).first()
    if found is None:
        raise InvalidFields({"supplier_id": [gettext("Choose one of your active suppliers.")]})
    return found


def _quantity_problem(product: Product, line: OrderLineInput) -> str | None:
    if line.entered_unit not in PurchaseOrderLine.EnteredUnit.values:
        return gettext("Choose the unit or the pack.")
    if line.entered_unit == "PACK" and product.pack_unit_id is None:
        return fill(
            gettext("%(code)s has no pack size. Enter the quantity in %(code2)s."),
            {
                "code": product.code,
                "code2": product.unit.code,
            },
        )
    unit = product.pack_unit if line.entered_unit == "PACK" else product.unit
    if line.entered_qty <= 0:
        return gettext("Enter a quantity above 0.")
    if line.entered_qty != line.entered_qty.quantize(QTY_STEP):
        return gettext("Enter a quantity with at most 3 decimals.")
    if unit is not None and not unit.allows_decimal and line.entered_qty % 1:
        return fill(gettext("%(code)s is counted in whole numbers."), {"code": unit.code})
    return None


def _lines(
    data: OrderInput, supplier: Supplier, by: User, existing: dict[UUID, PurchaseOrderLine]
) -> list[PurchaseOrderLine]:
    errors: dict[str, list[str]] = {}
    if not data.lines:
        errors["lines"] = [gettext("Add at least one product.")]
    elif len(data.lines) > MAX_LINES:
        errors["lines"] = [
            fill(
                gettext("A purchase order can have up to %(max_lines)s lines."),
                {"max_lines": MAX_LINES},
            )
        ]
    costs = sees_costs(by)
    if not costs and any(line.entered_cost is not None for line in data.lines):
        errors["lines"] = [gettext("Only staff who can see costs can enter them.")]
    if errors:
        raise InvalidFields(errors)
    ids = {line.product_id for line in data.lines}
    products = {
        p.pk: p
        for p in Product.objects.filter(pk__in=ids, deleted_at__isnull=True).select_related(
            "unit", "pack_unit"
        )
    }
    links = {
        link.product_id: link
        for link in SupplierProduct.objects.filter(supplier=supplier, product_id__in=ids)
    }
    rates = tax_rates_on(list(ids))
    rows: list[PurchaseOrderLine] = []
    seen: set[UUID] = set()
    for index, line in enumerate(data.lines, start=1):
        key = f"lines.{index}"
        product = products.get(line.product_id)
        if product is None:
            errors[key] = [gettext("Choose an existing product.")]
            continue
        if product.pk in seen:
            errors[key] = [
                fill(
                    gettext("%(code)s is already on this order. Change that line instead."),
                    {"code": product.code},
                )
            ]
            continue
        seen.add(product.pk)
        problem = _quantity_problem(product, line)
        if problem:
            errors[key] = [problem]
            continue
        if line.entered_cost is not None and line.entered_cost < 0:
            errors[key] = [gettext("Enter a cost of 0 or more.")]
            continue
        factor = product.pack_size if line.entered_unit == "PACK" else Decimal("1")
        assert factor is not None
        quantity = (line.entered_qty * factor).quantize(QTY_STEP)
        old = existing.get(line.id) if line.id else None
        link = links.get(product.pk)
        if line.entered_cost is not None:
            unit_cost: Decimal | None = cost_per_base_unit(line.entered_cost, factor)
        elif old is not None and old.product_id == product.pk and (not costs or old.unit_cost):
            unit_cost = old.unit_cost  # kept (never shown to staff who can't see costs)
        else:
            unit_cost = (link.last_unit_cost if link else None) or product.cost_price
        rate = rates.get(product.pk)
        rows.append(
            PurchaseOrderLine(
                line_no=index,
                product=product,
                product_code=product.code,
                product_name=product.name,
                supplier_code=link.supplier_code if link else "",
                unit_code=product.unit.code,
                entered_unit=line.entered_unit,
                entered_qty=line.entered_qty,
                quantity=quantity,
                unit_cost=unit_cost,
                gst_rate=rate.gst_rate if rate else Decimal("0"),
                line_total=stock_value(quantity, unit_cost) if unit_cost is not None else None,
                created_by=by,
            )
        )
    if errors:
        raise InvalidFields(errors)
    return rows


def _totals(order: PurchaseOrder, lines: Sequence[PurchaseOrderLine]) -> None:
    priced = [line for line in lines if line.line_total is not None]
    totals = [(line.line_total or Decimal("0"), line.gst_rate) for line in priced]
    order.subtotal = sum((total for total, _ in totals), Decimal("0.00"))
    order.estimated_tax = sum(
        (round2(total * rate / 100) for total, rate in totals), Decimal("0.00")
    )


def _save_lines(order: PurchaseOrder, rows: list[PurchaseOrderLine]) -> None:
    order.lines.all().delete()
    for row in rows:
        row.order = order
        row.tenant_id = order.tenant_id  # bulk_create skips TenantScopedModel.save
    PurchaseOrderLine.objects.bulk_create(rows)


def _check_expected(expected: date | None, before: date | None = None) -> None:
    if expected is not None and expected != before and expected < today_ist():
        raise InvalidFields({"expected_date": [gettext("The expected date can't be in the past.")]})


def _print_again(order: PurchaseOrder) -> None:
    """The copies are printed again after this transaction commits."""
    from apps.purchasing.tasks import render_order

    PurchaseOrder.objects.filter(pk=order.pk).update(pdf_status=PdfStatus.PENDING)
    order.pdf_status = PdfStatus.PENDING
    order_id, tenant_id = str(order.pk), str(order.tenant_id)
    transaction.on_commit(lambda: render_order.delay(order_id=order_id, tenant_id=tenant_id))


@transaction.atomic
def create_order(data: OrderInput, *, by: User) -> PurchaseOrder:
    supplier = _supplier(data.supplier_id)
    rows = _lines(data, supplier, by, {})
    _check_expected(data.expected_date)
    today = today_ist()
    order = PurchaseOrder(
        supplier=supplier,
        warehouse=stock.default_warehouse(),
        expected_date=data.expected_date or today + timedelta(days=lead_days(supplier)),
        notes=data.notes.strip(),
        created_by=by,
    )
    order.number = f"PO-{today.year}-{next_value('purchase_order', str(today.year)):05d}"
    _totals(order, rows)
    order.save()
    _save_lines(order, rows)
    audit.record(
        "purchasing.po_created",
        target=order,
        target_repr=order.number,
        metadata={"supplier": supplier.name, "lines": len(rows)},
    )
    _print_again(order)
    return order


def lock(order_id: UUID) -> PurchaseOrder:
    found: PurchaseOrder | None = (
        PurchaseOrder.objects.select_for_update().filter(pk=order_id).first()
    )
    if found is None:
        raise NotFound()
    return found


def _nothing_received(order: PurchaseOrder) -> bool:
    return not order.lines.filter(qty_received__gt=0).exists()


def _summary(order: PurchaseOrder) -> dict[str, Any]:
    return {
        "supplier": order.supplier_id,
        "expected_date": order.expected_date,
        "notes": order.notes,
        "lines": [
            [str(line.product_id), str(line.quantity), str(line.unit_cost)]
            for line in order.lines.all()
        ],
    }


@transaction.atomic
def update_order(order_id: UUID, data: OrderInput, *, by: User) -> PurchaseOrder:
    order = lock(order_id)
    if order.status not in (S.DRAFT, S.SENT) or not _nothing_received(order):
        raise NotEditable(
            gettext(
                "Something has been received against this order: only “Close the rest” is possible."
            )
            if order.status == S.PARTLY_RECEIVED
            else None
        )
    if order.status == S.SENT and data.supplier_id != order.supplier_id:
        raise InvalidFields(
            {
                "supplier_id": [
                    gettext("This order was sent to its supplier. Cancel it and start a new one.")
                ]
            }
        )
    supplier = _supplier(data.supplier_id)
    before = _summary(order)
    existing = {line.pk: line for line in order.lines.all()}
    rows = _lines(data, supplier, by, existing)
    _check_expected(data.expected_date, order.expected_date)
    order.supplier = supplier
    order.expected_date = data.expected_date or order.expected_date
    order.notes = data.notes.strip()
    _totals(order, rows)
    _save_lines(order, rows)
    after = _summary(order)
    if before == after:
        return order
    if order.status == S.SENT:
        order.changed_since_sent = True
    order.save()
    audit.record(
        "purchasing.po_changed",
        target=order,
        target_repr=order.number,
        changes=audit.diff(before, after),
    )
    _print_again(order)
    return order


@transaction.atomic
def delete_order(order_id: UUID, *, by: User) -> None:
    order = lock(order_id)
    if order.status != S.DRAFT:
        raise NotEditable(gettext("Only a draft can be deleted. Cancel a sent order instead."))
    audit.record("purchasing.po_deleted", target=order, target_repr=order.number)
    order.lines.all().delete()
    order.delete()


@dataclass(frozen=True)
class Sent:
    order: PurchaseOrder
    share_link: str  # for WhatsApp from a staff phone
    emailed: bool  # False: the supplier has no email address


@transaction.atomic
def send_order(order_id: UUID, *, by: User) -> Sent:
    """Mark the order sent (the next revision if it changed since), print the supplier's copy,
    email it to the supplier and give a link to share. Sending an unchanged order again just
    sends the same copy again."""
    from apps.notifications import links

    order = lock(order_id)
    if order.status not in (S.DRAFT, S.SENT) or not _nothing_received(order):
        raise NotEditable(
            gettext("Only a draft or a sent order with nothing received can be sent.")
        )
    supplier = _supplier(order.supplier_id)
    if not order.lines.exists():
        raise InvalidFields({"lines": [gettext("Add at least one product.")]})
    revised = order.status == S.DRAFT or order.changed_since_sent
    if revised:
        order.revision += 1
    order.status = S.SENT
    order.changed_since_sent = False
    order.sent_at, order.sent_by = timezone.now(), by
    order.supplier_snapshot = {
        "code": supplier.code,
        "name": supplier.name,
        "gstin": supplier.gstin or "",
        "state_code": supplier.state_id or "",
        "contact_name": supplier.contact_name,
        "phone": supplier.phone,
        "email": supplier.email,
        "address": ", ".join(
            x
            for x in (
                supplier.address_line1,
                supplier.address_line2,
                supplier.city,
                supplier.pincode,
            )
            if x
        ),
    }
    order.save()
    if revised:
        _print_again(order)
    audit.record(
        "purchasing.po_sent",
        target=order,
        target_repr=order.number,
        metadata={"revision": order.revision, "email": supplier.email or None},
    )
    emit(
        "purchase_order.sent",
        aggregate_type="purchase_order",
        aggregate_id=order.pk,
        payload={
            "purchase_order_id": str(order.pk),
            "supplier_id": str(supplier.pk),
            "revision": order.revision,
        },
    )
    from apps.platform.models import Tenant

    slug = Tenant.objects.values_list("slug", flat=True).get(pk=order.tenant_id)
    share = links.create(links.K.PURCHASE_ORDER, order.pk, slug)
    return Sent(order, share, bool(supplier.email))


def _no_open_receipt(order: PurchaseOrder) -> None:
    from apps.inventory.models import StockInward

    if StockInward.objects.filter(purchase_order=order, status=StockInward.Status.DRAFT).exists():
        raise NotEditable(
            gettext(
                "A goods receipt is being entered for this order. Post or delete that draft first."
            )
        )


def _cancel_due(order: PurchaseOrder) -> None:
    for line in order.lines.all():
        due = line.due
        if due > 0:
            line.qty_cancelled = line.qty_cancelled + due
            line.save(update_fields=["qty_cancelled", "updated_at"])


@transaction.atomic
def cancel_order(
    order_id: UUID, *, reason: str, by: User, notify_supplier: bool = True
) -> PurchaseOrder:
    """Before anything is received. A sent order needs a reason, and the supplier is emailed
    (``purchase_order.cancelled``, an editable text) unless staff say they have told them
    already. A draft was never sent: nobody is told."""
    order = lock(order_id)
    if order.status not in (S.DRAFT, S.SENT) or not _nothing_received(order):
        raise NotEditable(
            gettext("Something has been received against this order: use “Close the rest” instead.")
        )
    if order.status == S.SENT and not reason.strip():
        raise InvalidFields({"reason": [gettext("Say why the order is cancelled.")]})
    _no_open_receipt(order)
    was_sent = order.status == S.SENT
    _cancel_due(order)
    order.status = S.CANCELLED
    order.closed_at, order.closed_by, order.closed_reason = timezone.now(), by, reason.strip()[:300]
    order.save()
    told = was_sent and notify_supplier
    audit.record(
        "purchasing.po_cancelled",
        target=order,
        target_repr=order.number,
        metadata={"reason": order.closed_reason, "supplier_emailed": told},
    )
    _print_again(order)
    if told:
        emit(
            "purchase_order.cancelled",
            aggregate_type="purchase_order",
            aggregate_id=order.pk,
            payload={
                "purchase_order_id": str(order.pk),
                "supplier_id": str(order.supplier_id),
                "reason": order.closed_reason,
            },
        )
    return order


@transaction.atomic
def close_order(order_id: UUID, *, reason: str, by: User) -> PurchaseOrder:
    """After part of the goods arrived: what is still due is cancelled."""
    order = lock(order_id)
    if order.status != S.PARTLY_RECEIVED:
        raise NotEditable(
            gettext(
                "Only a partly received order can be closed. Cancel an order with nothing received."
            )
        )
    if not reason.strip():
        raise InvalidFields({"reason": [gettext("Say why the rest won't come.")]})
    _no_open_receipt(order)
    _cancel_due(order)
    order.status = S.CLOSED
    order.closed_at, order.closed_by, order.closed_reason = timezone.now(), by, reason.strip()[:300]
    order.save()
    audit.record(
        "purchasing.po_closed",
        target=order,
        target_repr=order.number,
        metadata={"reason": order.closed_reason},
    )
    _print_again(order)
    return order
