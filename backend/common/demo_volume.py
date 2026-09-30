"""Volume data for the speed check (ADR-050 item 13): three test distributors with 40,000, 5,000
and 5,000 orders over a year, for ``make perf``.

Staff, categories, brands, products and shops go through the normal services. The year of
trading does not: through the services one order placed, accepted, packed, dispatched, invoiced
and paid takes about 232 ms, so 50,000 orders would take over three hours. It is simulated in
time order here instead and bulk-inserted. Each order is placed (stock reserved, or backordered
while a product is out), accepted, packed and dispatched the next working day with its invoice,
then delivered and paid on time, late, in part or not at all. A few are cancelled or rejected, and
some deliveries are partly returned with a credit note. The simulation uses the services' tax
arithmetic, number formats, ledger postings, oldest-due-first matching and stock movements.
``reconcile()`` checks that the result agrees with itself the way the services keep it.

Left out: discounts and price lists, notifications, audit rows, outbox events and document PDFs
(the invoices' PDFs stay "being prepared"). DEBUG only, like ``seed``.
"""

from __future__ import annotations

import heapq
import itertools
import random
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any, NamedTuple
from uuid import UUID

from django.db import models
from django.db.models import F, Sum
from django.utils import timezone

from apps.accounts.models import Membership, Role, User
from apps.billing.invoicing import rounding_snapshot, seller_snapshot
from apps.billing.models import (
    CreditNote,
    CreditNoteLine,
    DocumentSeries,
    DocumentType,
    Invoice,
    InvoiceLine,
    PaymentStatus,
)
from apps.billing.numbering import default_prefix, format_number
from apps.billing.tax import (
    ComponentRounding,
    Components,
    LineTax,
    RoundOffMethod,
    SupplyType,
    amount_in_words,
    compute_document,
    compute_line,
    credit_for_quantity,
    credit_note_totals,
    due_date,
    financial_year,
    stock_value,
)
from apps.catalog import services as catalog
from apps.catalog.defaults import ensure_default_units
from apps.catalog.models import Product, Unit
from apps.inventory.defaults import ensure_default_warehouse
from apps.inventory.models import (
    MovementType,
    ReferenceType,
    StockInward,
    StockInwardLine,
    StockLevel,
    StockMovement,
    Warehouse,
)
from apps.ledger.models import Allocation, EntryType, LedgerEntry, RetailerAccount
from apps.orders.models import (
    Fulfilment,
    FulfilmentLine,
    Order,
    OrderEvent,
    OrderLine,
    OrderStatus,
    OrderStatusHistory,
)
from apps.orders.quote import supply_type_for
from apps.orders.services import _address_json, staff_label
from apps.payments.models import Payment
from apps.platform.models import Plan, Subscription, TaxRate, Tenant, TenantBranding, TenantProfile
from apps.platform.registry import SnapshotOn
from apps.platform.selectors import settings_snapshot
from apps.platform.validators import gstin_check_char
from apps.retailers.models import Retailer, RetailerAddress, RetailerUser
from apps.retailers.services import AddressInput, create_retailer
from common.dates import IST, today_ist
from common.demo import KINDS, SIZES, _brands, _categories, _money, _rate
from common.demo import _gstin as shop_gstin
from common.ids import uuid7
from common.models import Sequence
from common.tenancy import tenant_context

ZERO = Decimal("0")
QTY = Decimal("0.001")
BATCH = 2000
PASSWORD = "staff-dev-password"  # noqa: S105 - public demo value, as in ``seed``
QUANTITIES = (1, 2, 3, 4, 5, 6, 10, 12, 24)
QUANTITY_WEIGHTS = (10, 15, 10, 8, 8, 15, 8, 12, 4)
LINES = (1, 2, 3, 4, 5, 6, 7, 8, 10)
LINE_WEIGHTS = (8, 12, 16, 18, 16, 12, 8, 6, 4)
MODES = ("CASH", "UPI", "BANK_TRANSFER", "CHEQUE")
MODE_WEIGHTS = (40, 30, 20, 10)
COST_SNAPSHOT_DAYS = 270  # invoice lines older than this have no cost (issued before Phase 8)


@dataclass(frozen=True)
class VolumeTenant:
    slug: str
    name: str
    legal_name: str
    state_id: str
    pan: str
    city: str
    pincode: str
    orders: int
    shops: int
    products: int
    salespeople: int
    other_state: str  # where the shops in another state are
    phone_base: int


TENANTS = (
    VolumeTenant(
        "vol-a",
        "Volume Test A",
        "Volume Test A LLP",
        "27",
        "AAKFV1001A",
        "Pune",
        "411001",
        40_000,
        500,
        1_500,
        6,
        "24",
        9_300_000_000,
    ),
    VolumeTenant(
        "vol-b",
        "Volume Test B",
        "Volume Test B Private Limited",
        "24",
        "AAKCV2002B",
        "Ahmedabad",
        "380001",
        5_000,
        120,
        400,
        2,
        "27",
        9_300_100_000,
    ),
    VolumeTenant(
        "vol-c",
        "Volume Test C",
        "Volume Test C Private Limited",
        "29",
        "AAKCV3003C",
        "Bengaluru",
        "560001",
        5_000,
        120,
        400,
        2,
        "33",
        9_300_200_000,
    ),
)


class _Ids:
    """uuid7s that only go up: rows made at the same simulated moment keep the order they were
    made in when sorted by ``created_at``, then ``id`` (stock movements, ledger entries)."""

    def __init__(self) -> None:
        self.last = 0

    def __call__(self) -> UUID:
        self.last = max(uuid7().int, self.last + 1)
        return UUID(int=self.last)


new_id = _Ids()


def tenant_gstin(state: str, pan: str) -> str:
    first14 = f"{state}{pan}1Z"
    return first14 + gstin_check_char(first14)


@contextmanager
def backdated(*model_classes: type[models.Model]) -> Iterator[None]:
    """Let bulk inserts keep the ``created_at`` / ``updated_at`` they are given (the rows of a
    simulated past), instead of the time of the insert."""
    fields = [
        m._meta.get_field(name) for m in model_classes for name in ("created_at", "updated_at")
    ]
    saved = [(f, f.auto_now, f.auto_now_add) for f in fields]  # type: ignore[union-attr]
    for f in fields:
        f.auto_now = f.auto_now_add = False  # type: ignore[union-attr]
    try:
        yield
    finally:
        for f, now, add in saved:
            f.auto_now, f.auto_now_add = now, add  # type: ignore[union-attr]


def _ist(day: date, hours: float) -> datetime:
    return datetime.combine(day, time(0), tzinfo=IST) + timedelta(hours=hours)


def _next_working_day(day: date) -> date:
    day += timedelta(days=1)
    return day + timedelta(days=1) if day.weekday() == 6 else day


# --- Simulation state ----------------------------------------------------------------------------


@dataclass(eq=False, slots=True)
class Item:
    id: UUID
    code: str
    name: str
    hsn: str
    unit: str
    price: Decimal
    cost: Decimal
    rate: Decimal
    weight: float
    first_day: date  # first stocked
    last_day: date | None  # "dead": nothing ordered after this
    short: bool  # not restocked lately: runs out and is backordered
    daily: Decimal = ZERO  # expected demand per day, for restocking
    on_hand: Decimal = ZERO
    reserved: Decimal = ZERO
    backordered: Decimal = ZERO
    stocked: bool = False


@dataclass(eq=False, slots=True)
class Shop:
    id: UUID
    account_id: UUID
    user_id: UUID
    salesperson_id: UUID | None
    salesperson_label: str
    state: str
    supply: SupplyType
    terms: int
    buyer: dict[str, Any]
    address: dict[str, Any]
    weight: float
    from_day: date
    mode: str
    balance: Decimal = ZERO
    debits: Decimal = ZERO
    credits: Decimal = ZERO
    unapplied: Decimal = ZERO
    last_entry_at: datetime | None = None
    dues: list[Bill] = field(default_factory=list)
    money: list[Any] = field(default_factory=list)  # Receipt and Note with money left


@dataclass(eq=False, slots=True)
class Line:
    id: UUID
    no: int
    item: Item
    qty: Decimal
    tax: LineTax  # the estimate for the ordered quantity
    reserved: Decimal = ZERO
    backordered: Decimal = ZERO
    allocated: Decimal = ZERO
    cancelled: Decimal = ZERO
    dispatched: Decimal = ZERO
    delivered: Decimal = ZERO
    invoiced: Decimal = ZERO


@dataclass(eq=False, slots=True)
class Step:
    at: datetime
    from_status: str
    to_status: str
    event: str
    actor: UUID | None
    actor_type: str


@dataclass(eq=False, slots=True)
class Ord:
    id: UUID
    number: str
    shop: Shop
    placed_at: datetime
    placed_by: UUID
    via: str
    label: str
    lines: list[Line]
    totals: Any
    status: str = OrderStatus.PLACED
    backorder_state: str = Order.BackorderState.NONE
    hold_reason: str = ""
    accepted_at: datetime | None = None
    accepted_by: UUID | None = None
    closed_at: datetime | None = None
    cancelled_by: UUID | None = None
    reason: str = ""
    updated_at: datetime | None = None
    history: list[Step] = field(default_factory=list)
    shipment: Ship | None = None


@dataclass(eq=False, slots=True)
class Ship:
    id: UUID
    number: str
    order: Ord
    created_at: datetime
    lines: list[tuple[UUID, Line, Decimal]]
    status: str = Fulfilment.Status.ALLOCATED
    packed_at: datetime | None = None
    dispatched_at: datetime | None = None
    delivered_at: datetime | None = None


@dataclass(eq=False, slots=True)
class BillLine:
    id: UUID
    no: int
    line: Line
    ship_line_id: UUID
    qty: Decimal
    tax: LineTax
    unit_cost: Decimal | None


@dataclass(eq=False, slots=True)
class Bill:
    id: UUID
    number: str
    series_id: UUID
    fy: str
    order: Ord
    ship: Ship
    day: date
    due: date
    lines: list[BillLine]
    totals: Any
    seq: int
    created_at: datetime
    by: UUID
    paid: Decimal = ZERO
    credited: Decimal = ZERO
    balance: Decimal = ZERO
    updated_at: datetime | None = None


@dataclass(eq=False, slots=True)
class Note:
    id: UUID
    number: str
    series_id: UUID
    fy: str
    bill: Bill
    day: date
    part: BillLine
    qty: Decimal
    credit: Components
    totals: Any
    applied: Decimal
    reason: str
    seq: int
    created_at: datetime
    by: UUID
    unapplied: Decimal = ZERO


@dataclass(eq=False, slots=True)
class Receipt:
    id: UUID
    number: str
    shop: Shop
    amount: Decimal
    mode: str
    day: date
    seq: int
    created_at: datetime
    recorded_by: UUID
    collected_by: UUID | None
    unapplied: Decimal = ZERO


class MovementRow(NamedTuple):
    """A stock movement's fields (a tuple: there are hundreds of thousands)."""

    id: UUID
    created_at: datetime
    product_id: UUID
    movement_type: str
    quantity: Decimal
    delta_on_hand: Decimal
    delta_reserved: Decimal
    on_hand_after: Decimal
    reserved_after: Decimal
    unit_cost: Decimal | None
    value: Decimal | None
    reference_type: str
    reference_id: UUID
    reference_number: str
    reason: str
    created_by_id: UUID | None


class EntryRow(NamedTuple):
    id: UUID
    created_at: datetime
    account_id: UUID
    retailer_id: UUID
    entry_type: str
    entry_date: date
    debit: Decimal
    credit: Decimal
    balance_after: Decimal
    reference_type: str
    reference_id: UUID
    reference_number: str
    narration: str
    created_by_id: UUID | None


class AllocationRow(NamedTuple):
    id: UUID
    created_at: datetime
    retailer_id: UUID
    payment_id: UUID | None
    credit_note_id: UUID | None
    invoice_id: UUID
    amount: Decimal
    created_by_id: UUID | None


@dataclass
class Result:
    orders: int = 0
    invoices: int = 0
    credit_notes: int = 0
    payments: int = 0
    movements: int = 0
    ledger_entries: int = 0


class Simulation:
    """One distributor's year, event by event in time order."""

    def __init__(
        self,
        tenant: Tenant,
        spec: VolumeTenant,
        *,
        items: list[Item],
        shops: list[Shop],
        staff: dict[str, UUID],
        salespeople: list[UUID],
        warehouse_id: UUID,
        days: int,
        rng: random.Random,
    ) -> None:
        self.tenant, self.spec, self.rng = tenant, spec, rng
        self.items, self.shops, self.staff = items, shops, staff
        self.salespeople, self.warehouse_id = salespeople, warehouse_id
        self.now = timezone.now()
        self.today = today_ist()
        self.start = self.today - timedelta(days=days)
        snapshot = rounding_snapshot(tenant.pk)
        self.rounding_snapshot = snapshot
        self.rounding = ComponentRounding(snapshot["tax.component_rounding"])
        self.round_to_rupee = bool(snapshot["invoicing.round_to_rupee"])
        self.round_off = RoundOffMethod(snapshot["invoicing.round_off_method"])
        self.order_snapshot = settings_snapshot(SnapshotOn.ORDER, tenant.pk)
        self.seller = seller_snapshot(tenant)
        self.queue: list[tuple[datetime, int, str, Any]] = []
        self.clock = datetime.min.replace(tzinfo=IST)
        self.counter = itertools.count()
        self.numbers: Counter[tuple[str, str]] = Counter()
        self.series: dict[tuple[str, str], UUID] = {}
        self.orders: list[Ord] = []
        self.bills: list[Bill] = []
        self.notes: list[Note] = []
        self.receipts: list[Receipt] = []
        self.allocations: list[AllocationRow] = []
        self.ledger: list[EntryRow] = []
        self.movements: list[MovementRow] = []
        self.inwards: list[tuple[UUID, str, datetime, list[tuple[Item, Decimal]]]] = []
        self.handovers: dict[UUID, datetime] = {}
        self.cleared: dict[UUID, datetime] = {}
        self.bill_of_ship: dict[UUID, Bill] = {}
        self.prefixes = {t: default_prefix(t) for t in DocumentType.values}
        self._items_key: date | None = None
        self._items_cache: tuple[list[Item], list[float]] = ([], [])
        self._shops_key: date | None = None
        self._shops_cache: tuple[list[Shop], list[float]] = ([], [])

    # --- Scheduling ---

    def at(self, when: datetime, kind: str, subject: Any) -> None:
        """Schedule an event, never before the one being handled (a payment planned for the
        invoice's day can't come before its dispatch that day); events after now are dropped."""
        when = max(when, self.clock)
        if when <= self.now:
            heapq.heappush(self.queue, (when, next(self.counter), kind, subject))

    def number(self, name: str, period: str) -> int:
        self.numbers[(name, period)] += 1
        return self.numbers[(name, period)]

    def document_number(self, document_type: str, day: date) -> tuple[UUID, str, str]:
        fy = financial_year(day)
        if (document_type, fy) not in self.series:
            self.series[(document_type, fy)] = new_id()
        n = self.number(document_type, fy)
        return (
            self.series[(document_type, fy)],
            format_number(self.prefix(document_type), fy, n),
            fy,
        )

    def prefix(self, document_type: str) -> str:
        return self.prefixes[document_type]

    def run(self) -> None:
        self._plan_demand()
        order_days = Counter(
            self.rng.choices(
                range(self._days() + 1),
                weights=[self._busy(d) for d in self._dates()],
                k=self.spec.orders,
            )
        )
        for offset, day in enumerate(self._dates()):
            self.at(_ist(day, 7), "restock", day)
            if order_days[offset]:
                self.at(_ist(day, 0), "day", (day, order_days[offset]))
        while self.queue:
            when, _n, kind, subject = heapq.heappop(self.queue)
            self.clock = when
            getattr(self, f"_on_{kind}")(when, subject)

    def _days(self) -> int:
        return (self.today - self.start).days

    def _dates(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(self._days() + 1)]

    def _busy(self, day: date) -> float:
        """Business grows through the year; Sundays are quiet, Saturdays a little."""
        growth = 0.6 + 0.7 * (day - self.start).days / max(self._days(), 1)
        return growth * {6: 0.35, 5: 0.9}.get(day.weekday(), 1.0)

    def _plan_demand(self) -> None:
        total = sum(i.weight for i in self.items) or 1.0
        mean_lines = sum(n * w for n, w in zip(LINES, LINE_WEIGHTS, strict=True)) / sum(
            LINE_WEIGHTS
        )
        mean_qty = sum(q * w for q, w in zip(QUANTITIES, QUANTITY_WEIGHTS, strict=True)) / sum(
            QUANTITY_WEIGHTS
        )
        per_day = self.spec.orders / max(self._days(), 1) * 1.4  # the busiest months
        for item in self.items:
            daily = per_day * mean_lines * mean_qty * item.weight / total
            item.daily = Decimal(max(1, round(daily, 1))).quantize(Decimal("0.1"))

    # --- Stock ---

    def _move(
        self,
        when: datetime,
        item: Item,
        kind: str,
        qty: Decimal,
        ref: tuple[str, UUID, str],
        *,
        by: UUID | None,
        unit_cost: Decimal | None = None,
        reason: str = "",
    ) -> None:
        on_hand = {"INWARD": 1, "RETURN": 1, "SALE": -1}.get(kind, 0) * qty
        reserved = {"RESERVE": 1, "RELEASE": -1, "SALE": -1}.get(kind, 0) * qty
        item.on_hand += on_hand
        item.reserved += reserved
        if item.on_hand < 0 or item.reserved < 0 or item.reserved > item.on_hand:
            raise AssertionError(f"stock of {item.code} went wrong at {when}")
        self.movements.append(
            MovementRow(
                new_id(),
                when,
                item.id,
                kind,
                qty,
                on_hand,
                reserved,
                item.on_hand,
                item.reserved,
                unit_cost,
                None if unit_cost is None else stock_value(qty, unit_cost),
                *ref,
                reason,
                by,
            )
        )

    def _receive(self, when: datetime, lines: list[tuple[Item, Decimal]]) -> None:
        year = str(when.astimezone(IST).year)
        number = f"GRN-{year}-{self.number('GRN', year):05d}"
        inward_id = new_id()
        self.inwards.append((inward_id, number, when, lines))
        for item, qty in lines:
            item.stocked = True
            self._move(
                when,
                item,
                MovementType.INWARD,
                qty,
                (ReferenceType.INWARD, inward_id, number),
                by=self.staff["WAREHOUSE"],
                unit_cost=item.cost,
            )

    @staticmethod
    def _dozen(qty: Decimal) -> Decimal:
        return max(Decimal(12), (qty / 12).to_integral_value(ROUND_CEILING) * 12)

    def _on_restock(self, when: datetime, day: date) -> None:
        """Each morning a goods receipt for what runs low: 6 weeks' demand when below 2 weeks'.
        Products running short are not restocked in the last 60 days; dead ones after their last
        order."""
        lines: list[tuple[Item, Decimal]] = []
        for item in self.items:
            if item.first_day > day or (item.last_day and day > item.last_day):
                continue
            if item.short and day >= self.today - timedelta(days=60) and item.stocked:
                continue
            available = item.on_hand - item.reserved
            if not item.stocked:
                lines.append((item, self._dozen(item.daily * 60)))
            elif available < item.daily * 14:
                lines.append((item, self._dozen(item.daily * 42)))
        if lines:
            self._receive(when, lines)

    # --- Orders ---

    def _eligible_items(self, day: date) -> tuple[list[Item], list[float]]:
        """Products that can be ordered on ``day`` with their cumulative weights (per day)."""
        if self._items_key != day:
            chosen = [
                i
                for i in self.items
                if i.first_day <= day and not (i.last_day and day > i.last_day)
            ]
            self._items_cache = (chosen, list(itertools.accumulate(i.weight for i in chosen)))
            self._items_key = day
        return self._items_cache

    def _eligible_shops(self, day: date) -> tuple[list[Shop], list[float]]:
        if self._shops_key != day:
            chosen = [s for s in self.shops if s.from_day <= day]
            self._shops_cache = (chosen, list(itertools.accumulate(s.weight for s in chosen)))
            self._shops_key = day
        return self._shops_cache

    def _on_day(self, _when: datetime, subject: tuple[date, int]) -> None:
        day, count = subject
        now_ist = self.now.astimezone(IST)
        for _ in range(count):
            if day == self.today:
                hours = self.rng.uniform(0, max(0.1, now_ist.hour + now_ist.minute / 60 - 0.05))
            else:
                hours = self.rng.uniform(8, 21)
            self.at(_ist(day, hours), "place", day)

    def _tax(self, item: Item, qty: Decimal, supply: SupplyType) -> LineTax:
        return compute_line(
            qty=qty,
            unit_price=item.price,
            rate=item.rate,
            supply_type=supply,
            discount_amount=ZERO,
            rounding=self.rounding,
        )

    def _totals(self, taxes: list[LineTax]) -> Any:
        return compute_document(
            taxes, round_to_rupee=self.round_to_rupee, round_off_method=self.round_off
        )

    def _on_place(self, when: datetime, day: date) -> None:
        rng = self.rng
        shops, shop_weights = self._eligible_shops(day)
        items, item_weights = self._eligible_items(day)
        if not shops or not items:
            return
        shop = rng.choices(shops, cum_weights=shop_weights)[0]
        wanted = min(rng.choices(LINES, LINE_WEIGHTS)[0], len(items))
        picked: dict[UUID, Item] = {}
        while len(picked) < wanted:
            for item in rng.choices(items, cum_weights=item_weights, k=wanted):
                picked.setdefault(item.id, item)
        chosen = sorted(list(picked.values())[:wanted], key=lambda i: i.id)
        year = str(when.astimezone(IST).year)
        number = f"ORD-{year}-{self.number('ORDER', year):06d}"
        salesperson = shop.salesperson_id
        by_staff = salesperson is not None and rng.random() < 0.2
        placed_by: UUID = salesperson if by_staff and salesperson else shop.user_id
        lines = []
        for no, item in enumerate(chosen, 1):
            qty = Decimal(rng.choices(QUANTITIES, QUANTITY_WEIGHTS)[0])
            lines.append(Line(new_id(), no, item, qty, self._tax(item, qty, shop.supply)))
        order = Ord(
            id=new_id(),
            number=number,
            shop=shop,
            placed_at=when,
            placed_by=placed_by,
            via=Order.PlacedVia.STAFF if by_staff else Order.PlacedVia.RETAILER_APP,
            label=shop.salesperson_label if by_staff else "",
            lines=lines,
            totals=self._totals([line.tax for line in lines]),
            updated_at=when,
        )
        self.orders.append(order)
        recent = day >= self.today - timedelta(days=2)
        fate = rng.random()
        hold = recent and fate < 0.05
        order.status = OrderStatus.ON_HOLD if hold else OrderStatus.PLACED
        order.hold_reason = Order.HoldReason.CREDIT_LIMIT if hold else ""
        order.history.append(
            Step(
                when,
                "",
                order.status,
                OrderEvent.PLACE,
                order.placed_by,
                "STAFF" if by_staff else "RETAILER",
            )
        )
        for line in lines:
            item = line.item
            available = item.on_hand - item.reserved
            if available < line.qty and not (item.short and item.stocked):
                self._receive(when, [(item, self._dozen(item.daily * 42 + line.qty))])
                available = item.on_hand - item.reserved
            line.reserved = min(available, line.qty)
            line.backordered = line.qty - line.reserved
            if line.reserved:
                self._move(
                    when,
                    item,
                    MovementType.RESERVE,
                    line.reserved,
                    (ReferenceType.ORDER_LINE, line.id, number),
                    by=order.placed_by,
                )
            item.backordered += line.backordered
        if hold:
            return
        if not recent and fate < 0.02:
            self.at(when + timedelta(hours=rng.uniform(0.3, 5)), "cancel", order)
        elif not recent and fate < 0.03:
            self.at(when + timedelta(hours=rng.uniform(0.2, 3)), "reject", order)
        else:
            self.at(when + timedelta(hours=rng.uniform(0.2, 4)), "accept", order)

    def _close_unfilled(self, when: datetime, order: Ord, by: UUID | None) -> None:
        for line in order.lines:
            if line.reserved:
                self._move(
                    when,
                    line.item,
                    MovementType.RELEASE,
                    line.reserved,
                    (ReferenceType.ORDER_LINE, line.id, order.number),
                    by=by,
                )
            line.item.backordered -= line.backordered
            line.cancelled, line.reserved, line.backordered = line.qty, ZERO, ZERO
        order.closed_at = order.updated_at = when

    def _on_cancel(self, when: datetime, order: Ord) -> None:
        by_shop = self.rng.random() < 0.5
        by = order.shop.user_id if by_shop else self.staff["OWNER"]
        self._close_unfilled(when, order, by)
        order.history.append(
            Step(
                when,
                order.status,
                OrderStatus.CANCELLED,
                OrderEvent.CANCEL,
                by,
                "RETAILER" if by_shop else "STAFF",
            )
        )
        order.status, order.cancelled_by = OrderStatus.CANCELLED, by
        order.reason = "Ordered by mistake" if by_shop else "Shop asked to cancel"

    def _on_reject(self, when: datetime, order: Ord) -> None:
        by = self.staff["OWNER"]
        self._close_unfilled(when, order, by)
        order.history.append(
            Step(when, order.status, OrderStatus.REJECTED, OrderEvent.REJECT, by, "STAFF")
        )
        order.status, order.reason = OrderStatus.REJECTED, "Outside our delivery area"

    def _on_accept(self, when: datetime, order: Ord) -> None:
        by = self.staff["MANAGER"]
        order.history.append(
            Step(when, order.status, OrderStatus.ACCEPTED, OrderEvent.ACCEPT, by, "STAFF")
        )
        order.status, order.accepted_at, order.accepted_by = OrderStatus.ACCEPTED, when, by
        order.updated_at = when
        shipped = []
        for line in order.lines:
            line.allocated, line.reserved = line.reserved, ZERO
            if line.allocated:
                shipped.append((new_id(), line, line.allocated))
        if any(line.backordered for line in order.lines):
            order.backorder_state = Order.BackorderState.OPEN
        if not shipped:
            return
        order.shipment = Ship(new_id(), f"{order.number}/1", order, when, shipped)
        day = _next_working_day(when.astimezone(IST).date())
        self.at(_ist(day, self.rng.uniform(9, 13)), "pack", order.shipment)

    def _on_pack(self, when: datetime, ship: Ship) -> None:
        by = self.staff["WAREHOUSE"]
        ship.status, ship.packed_at = Fulfilment.Status.PACKED, when
        ship.order.history.append(
            Step(when, ship.order.status, OrderStatus.PACKED, OrderEvent.PACK, by, "STAFF")
        )
        ship.order.status, ship.order.updated_at = OrderStatus.PACKED, when
        self.at(when + timedelta(hours=self.rng.uniform(0.5, 3)), "dispatch", ship)

    def _on_dispatch(self, when: datetime, ship: Ship) -> None:
        by = self.staff["WAREHOUSE"]
        order = ship.order
        for _id, line, qty in ship.lines:
            self._move(
                when,
                line.item,
                MovementType.SALE,
                qty,
                (ReferenceType.FULFILMENT, ship.id, ship.number),
                by=by,
            )
            line.dispatched += qty
        ship.status, ship.dispatched_at = Fulfilment.Status.DISPATCHED, when
        order.history.append(
            Step(when, order.status, OrderStatus.DISPATCHED, OrderEvent.DISPATCH, by, "STAFF")
        )
        order.status, order.updated_at = OrderStatus.DISPATCHED, when
        bill = self._invoice(when, ship, by)
        self._plan_payments(bill)
        self.at(when + timedelta(hours=self.rng.uniform(3, 30)), "deliver", ship)

    def _on_deliver(self, when: datetime, ship: Ship) -> None:
        by = self.staff["WAREHOUSE"]
        order = ship.order
        for _id, line, qty in ship.lines:
            line.delivered += qty
        ship.status, ship.delivered_at = Fulfilment.Status.DELIVERED, when
        waiting = any(line.backordered for line in order.lines)
        status = OrderStatus.PARTLY_DELIVERED if waiting else OrderStatus.COMPLETED
        order.history.append(Step(when, order.status, status, OrderEvent.DELIVER, by, "STAFF"))
        order.status, order.updated_at = status, when
        if not waiting:
            order.closed_at = when
        returnable = [bl for bl in self._bill_of(ship).lines if not bl.line.item.short]
        if returnable and self.rng.random() < 0.015:
            later = when + timedelta(days=self.rng.uniform(1, 15))
            self.at(later, "return", (self._bill_of(ship), self.rng.choice(returnable)))

    # --- Money ---

    def _bill_of(self, ship: Ship) -> Bill:
        return self.bill_of_ship[ship.id]

    def _invoice(self, when: datetime, ship: Ship, by: UUID) -> Bill:
        order, shop = ship.order, ship.order.shop
        day = when.astimezone(IST).date()
        series_id, number, fy = self.document_number(DocumentType.INVOICE, day)
        costed = day >= self.today - timedelta(days=COST_SNAPSHOT_DAYS)
        lines = []
        for no, (ship_line_id, line, qty) in enumerate(ship.lines, 1):
            tax = line.tax if qty == line.qty else self._tax(line.item, qty, shop.supply)
            lines.append(
                BillLine(
                    new_id(), no, line, ship_line_id, qty, tax, line.item.cost if costed else None
                )
            )
            line.invoiced += qty
        totals = self._totals([bl.tax for bl in lines])
        bill = Bill(
            id=new_id(),
            number=number,
            series_id=series_id,
            fy=fy,
            order=order,
            ship=ship,
            day=day,
            due=due_date(day, shop.terms),
            lines=lines,
            totals=totals,
            seq=next(self.counter),
            created_at=when,
            by=by,
            balance=totals.grand_total,
            updated_at=when,
        )
        self.bills.append(bill)
        self.bill_of_ship[ship.id] = bill
        self._post(
            when,
            shop,
            EntryType.INVOICE,
            debit=totals.grand_total,
            day=day,
            ref=("INVOICE", bill.id, number),
            narration=f"Invoice for order {order.number}",
            by=by,
        )
        shop.dues.append(bill)
        self._settle(when, shop, by)
        return bill

    def _plan_payments(self, bill: Bill) -> None:
        """On time, late, very late, in two parts, or not at all."""
        rng, due = self.rng, bill.due
        fate = rng.random()
        plan: list[tuple[date, Decimal]]
        if fate < 0.62:
            plan = [(bill.day + timedelta(days=rng.randint(0, bill.order.shop.terms)), Decimal(1))]
        elif fate < 0.84:
            plan = [(due + timedelta(days=rng.randint(1, 30)), Decimal(1))]
        elif fate < 0.90:
            plan = [(due + timedelta(days=rng.randint(31, 100)), Decimal(1))]
        elif fate < 0.94:
            plan = [
                (due + timedelta(days=rng.randint(0, 20)), Decimal("0.5")),
                (due + timedelta(days=rng.randint(21, 60)), Decimal(1)),
            ]
        else:
            plan = []
        for day, share in plan:
            self.at(_ist(day, rng.uniform(11, 19)), "pay", (bill, share))

    def _on_pay(self, when: datetime, subject: tuple[Bill, Decimal]) -> None:
        bill, share = subject
        if bill.balance <= 0:
            return
        amount = (
            bill.balance
            if share == 1
            else max(Decimal(1), (bill.balance * share).quantize(Decimal(1)))
        )
        shop, rng = bill.order.shop, self.rng
        mode = shop.mode if rng.random() < 0.8 else rng.choices(MODES, MODE_WEIGHTS)[0]
        day = when.astimezone(IST).date()
        collected = mode == "CASH" and shop.salesperson_id is not None and rng.random() < 0.7
        collector = shop.salesperson_id
        recorded_by: UUID = collector if collected and collector else self.staff["ACCOUNTS"]
        _series, number, _fy = self.document_number(DocumentType.RECEIPT, day)
        receipt = Receipt(
            id=new_id(),
            number=number,
            shop=shop,
            amount=amount,
            mode=mode,
            day=day,
            seq=next(self.counter),
            created_at=when,
            recorded_by=recorded_by,
            collected_by=shop.salesperson_id if collected else None,
            unapplied=amount,
        )
        self.receipts.append(receipt)
        if collected:
            handed = when + timedelta(days=rng.uniform(0.5, 3))
            if handed <= self.now:
                self.handovers[receipt.id] = handed
        if mode == "CHEQUE":
            cleared = when + timedelta(days=rng.uniform(2, 4))
            if cleared <= self.now:
                self.cleared[receipt.id] = cleared
        label = dict(Payment.Mode.choices)[mode]
        self._post(
            when,
            shop,
            EntryType.PAYMENT,
            credit=amount,
            day=day,
            ref=("PAYMENT", receipt.id, number),
            narration=f"{label} received",
            by=recorded_by,
        )
        shop.unapplied += amount
        shop.money.append(receipt)
        self._settle(when, shop, recorded_by)

    def _on_return(self, when: datetime, subject: tuple[Bill, BillLine]) -> None:
        bill, part = subject
        shop, rng, by = bill.order.shop, self.rng, self.staff["WAREHOUSE"]
        qty = max(Decimal(1), (part.qty * Decimal(rng.uniform(0.1, 0.5))).quantize(Decimal(1)))
        qty = min(qty, part.qty)
        credit = credit_for_quantity(
            qty,
            invoiced_qty=part.qty,
            remaining_qty=part.qty,
            line=part.tax,
            remaining=Components.of(part.tax),
            rounding=self.rounding,
        )
        if credit.taxable <= 0:
            return
        exhausts = len(bill.lines) == 1 and qty == part.qty
        totals = credit_note_totals(
            [credit],
            round_to_rupee=self.round_to_rupee,
            round_off_method=self.round_off,
            invoice_left=bill.totals.grand_total if exhausts else None,
        )
        day = when.astimezone(IST).date()
        series_id, number, fy = self.document_number(DocumentType.CREDIT_NOTE, day)
        applied = min(totals.grand_total, bill.balance)
        note = Note(
            id=new_id(),
            number=number,
            series_id=series_id,
            fy=fy,
            bill=bill,
            day=day,
            part=part,
            qty=qty,
            credit=credit,
            totals=totals,
            applied=applied,
            reason=rng.choice(("DAMAGED", "EXPIRED", "WRONG_ITEM")),
            seq=next(self.counter),
            created_at=when,
            by=by,
            unapplied=totals.grand_total,
        )
        self.notes.append(note)
        self._post(
            when,
            shop,
            EntryType.CREDIT_NOTE,
            credit=totals.grand_total,
            day=day,
            ref=("CREDIT_NOTE", note.id, number),
            narration=f"Credit note against {bill.number}",
            by=by,
        )
        shop.unapplied += totals.grand_total
        shop.money.append(note)
        if applied > 0:
            self._apply(when, shop, note, bill, applied, by)
        self._settle(when, shop, by)
        self._move(
            when,
            part.line.item,
            MovementType.RETURN,
            qty,
            (ReferenceType.CREDIT_NOTE, note.id, number),
            by=by,
            reason=f"Returned on {number}",
        )

    def _post(
        self,
        when: datetime,
        shop: Shop,
        entry_type: str,
        *,
        day: date,
        ref: tuple[str, UUID, str],
        narration: str,
        by: UUID | None,
        debit: Decimal = ZERO,
        credit: Decimal = ZERO,
    ) -> None:
        shop.debits += debit
        shop.credits += credit
        shop.balance = shop.debits - shop.credits
        shop.last_entry_at = when
        self.ledger.append(
            EntryRow(
                new_id(),
                when,
                shop.account_id,
                shop.id,
                entry_type,
                day,
                debit,
                credit,
                shop.balance,
                *ref,
                narration[:300],
                by,
            )
        )

    def _apply(
        self, when: datetime, shop: Shop, source: Any, bill: Bill, amount: Decimal, by: UUID | None
    ) -> None:
        receipt = isinstance(source, Receipt)
        self.allocations.append(
            AllocationRow(
                new_id(),
                when,
                shop.id,
                source.id if receipt else None,
                None if receipt else source.id,
                bill.id,
                amount,
                by,
            )
        )
        source.unapplied -= amount
        if isinstance(source, Receipt):
            bill.paid += amount
        else:
            bill.credited += amount
        bill.balance -= amount
        bill.updated_at = when
        shop.unapplied -= amount

    def _settle(self, when: datetime, shop: Shop, by: UUID | None) -> None:
        """Oldest money against the earliest dues (``allocation.settle``)."""
        money = sorted(
            (m for m in shop.money if m.unapplied > 0), key=lambda m: (m.day, m.created_at, m.seq)
        )
        dues = sorted(
            (b for b in shop.dues if b.balance > 0), key=lambda b: (b.due, b.day, b.created_at)
        )
        for source in money:
            for bill in dues:
                if source.unapplied <= 0:
                    break
                if bill.balance <= 0:
                    continue
                self._apply(when, shop, source, bill, min(source.unapplied, bill.balance), by)
        shop.money = [m for m in shop.money if m.unapplied > 0]
        shop.dues = [b for b in shop.dues if b.balance > 0]


# --- Master data, through the services -----------------------------------------------------------

OTHER_PLACES = {"24": ("Surat", "395003"), "27": ("Mumbai", "400001"), "33": ("Chennai", "600001")}
SHOP_WORDS = ("Laxmi", "Sai", "Balaji", "Shiv", "Maruti", "Annapurna", "Krishna", "Ambe", "Ganesh")
SHOP_KINDS = ("Stores", "Kirana", "Traders", "Provision", "Mart", "General Store")


def setup_tenant(spec: VolumeTenant) -> Tenant:
    tenant, _created = Tenant.objects.update_or_create(
        slug=spec.slug,
        defaults={
            "name": spec.name,
            "legal_name": spec.legal_name,
            "state_id": spec.state_id,
            "pan": spec.pan,
            "gstin": tenant_gstin(spec.state_id, spec.pan),
            "address_line1": "1 Industrial Estate",
            "city": spec.city,
            "pincode": spec.pincode,
            "email": f"accounts@{spec.slug}.example.com",
            "phone": "02000000000",
            "status": Tenant.Status.ACTIVE,
        },
    )
    with tenant_context(tenant.pk):
        TenantProfile.objects.get_or_create(tenant=tenant)
        TenantBranding.objects.update_or_create(
            tenant=tenant, defaults={"display_name": spec.name, "primary_color": "#475569"}
        )
        if not Subscription.objects.filter(is_current=True).exists():
            plan = Plan.objects.get(is_default=True)
            Subscription.objects.create(tenant=tenant, plan=plan, starts_at=timezone.now())
        ensure_default_units(Unit)
        ensure_default_warehouse(Warehouse)
    return tenant


def setup_staff(spec: VolumeTenant) -> tuple[dict[str, UUID], list[UUID]]:
    """owner@, manager@, warehouse@, accounts@ and sales1@ … sales<n>@<slug>.example.com."""
    roles = {r.code: r for r in Role.objects.filter(tenant__isnull=True, is_platform=False)}

    def login(email: str, name: str, code: str) -> UUID:
        user = User.objects.filter(email=email).first() or User.objects.create_user(
            email, PASSWORD, user_type=User.UserType.STAFF, full_name=name
        )
        Membership.objects.get_or_create(user=user, defaults={"role": roles[code]})
        pk: UUID = user.pk
        return pk

    staff = {
        code: login(
            f"{code.lower()}@{spec.slug}.example.com", f"{code.title()} ({spec.name})", code
        )
        for code in ("OWNER", "MANAGER", "WAREHOUSE", "ACCOUNTS")
    }
    sales = [
        login(f"sales{n}@{spec.slug}.example.com", f"Sales {n} ({spec.name})", "SALES")
        for n in range(1, spec.salespeople + 1)
    ]
    return staff, sales


def setup_items(
    tenant: Tenant, spec: VolumeTenant, by: User, rng: random.Random, start: date, today: date
) -> list[Item]:
    """The catalog through ``catalog.create_product``; then who sells how much: a long tail of
    popularity, 5% dead (nothing ordered for the last 100-200 days), 4% new (first stocked in
    the last 80 days) and 2% running short (not restocked in the last 60 days)."""
    leaves = _categories(by)
    brands, own_brand = _brands(tenant, by)
    units = {u.code: u for u in Unit.objects.all()}
    active = set(TaxRate.objects.filter(is_active=True, rate__gt=0).values_list("rate", flat=True))
    prefix = f"V{spec.slug[-1].upper()}"
    existing = set(
        Product.objects.filter(code__startswith=f"{prefix}-").values_list("code", flat=True)
    )
    for n in range(1, spec.products + 1):
        code = f"{prefix}-{n:05d}"
        price = _money(Decimal(rng.randrange(800, 60000)) / 100)
        category, hsn, preferred = leaves[n % len(leaves)]
        brand = own_brand if n % 10 == 0 else brands[(n * 7) % len(brands)]
        kind, size = rng.choice(KINDS[category.name]), rng.choice(SIZES)
        if code in existing:
            continue
        catalog.create_product(
            {
                "code": code,
                "name": f"{brand.name} {kind} {size}",
                "category_id": category.pk,
                "brand_id": brand.pk,
                "unit_id": units["PCS"].pk,
                "hsn_code": hsn,
                "mrp": _money(price * Decimal("1.4")),
                "base_price": price,
                "cost_price": _money(price * Decimal("0.82" if brand.own_brand else "0.9")),
                "min_order_qty": Decimal("1"),
                "order_multiple": Decimal("1"),
                "reorder_level": Decimal("24"),
            },
            gst_rate=_rate(preferred, active),
            by=by,
        )
    from apps.catalog.selectors import tax_rates_on

    products = list(
        Product.objects.filter(code__startswith=f"{prefix}-")
        .select_related("unit")
        .order_by("code")
    )
    rates = tax_rates_on([p.pk for p in products], today)
    ranks = list(range(1, len(products) + 1))
    rng.shuffle(ranks)
    items = []
    for product, rank in zip(products, ranks, strict=True):
        fate = rng.random()
        items.append(
            Item(
                id=product.pk,
                code=product.code,
                name=product.name,
                hsn=product.hsn_code,
                unit=product.unit.code,
                price=Decimal(product.base_price),
                cost=Decimal(product.cost_price or 0),
                rate=Decimal(rates[product.pk].gst_rate),
                weight=1 / rank**0.9,
                first_day=today - timedelta(days=rng.randint(10, 80))
                if 0.05 <= fate < 0.09
                else start,
                last_day=today - timedelta(days=rng.randint(100, 200)) if fate < 0.05 else None,
                short=0.09 <= fate < 0.11,
            )
        )
    return items


def setup_shops(
    tenant: Tenant,
    spec: VolumeTenant,
    by: User,
    salespeople: list[UUID],
    rng: random.Random,
    start: date,
    today: date,
) -> list[Shop]:
    """Shops through ``create_retailer``: 10% in another state, 40% with a GSTIN, 90% with a
    salesperson; a quarter join during the year; a few order far more than the rest."""
    for i in range(spec.shops):
        phone = str(spec.phone_base + i)
        if Retailer.objects.filter(mobile=f"+91{phone}").exists():
            continue
        other = i % 10 == 9
        state = spec.other_state if other else spec.state_id
        city, pincode = OTHER_PLACES[state] if other else (spec.city, spec.pincode)
        name = f"{SHOP_WORDS[i % len(SHOP_WORDS)]} {SHOP_KINDS[i % len(SHOP_KINDS)]} {i + 1}"
        create_retailer(
            shop_name=name,
            phone=phone,
            contact_name=f"Owner {i + 1}",
            created_by=by,
            state_id=state,
            gstin=shop_gstin(state, rng) if i % 5 < 2 else None,
            billing=AddressInput(
                line1=f"Shop {i + 1}, Market Road", city=city, pincode=pincode, state_id=state
            ),
            extra={
                "salesperson_id": salespeople[i % len(salespeople)] if i % 10 else None,
                "payment_terms_days": (15, 30, 45)[i % 3],
                "credit_limit": Decimal("500000"),
            },
            send_welcome=False,
        )
    labels = {pk: staff_label(User.objects.get(pk=pk)) for pk in salespeople}
    users = dict(RetailerUser.objects.values_list("retailer_id", "user_id"))
    accounts = dict(RetailerAccount.objects.values_list("retailer_id", "id"))
    addresses = {
        a.retailer_id: _address_json(a)
        for a in RetailerAddress.objects.filter(kind="BILLING", is_default=True).select_related(
            "state"
        )
    }
    retailers = list(Retailer.objects.filter(deleted_at__isnull=True).order_by("code"))
    ranks = list(range(1, len(retailers) + 1))
    rng.shuffle(ranks)
    shops = []
    for retailer, rank in zip(retailers, ranks, strict=True):
        address = addresses.get(retailer.pk, {})
        shops.append(
            Shop(
                id=retailer.pk,
                account_id=accounts[retailer.pk],
                user_id=users[retailer.pk],
                salesperson_id=retailer.salesperson_id,
                salesperson_label=labels.get(retailer.salesperson_id, ""),
                state=retailer.state_id,
                supply=supply_type_for(tenant.state_id, retailer.state_id),
                terms=retailer.payment_terms_days,
                buyer={
                    "name": retailer.shop_name,
                    "code": retailer.code,
                    "contact": retailer.owner_name,
                    "phone": retailer.mobile,
                    "gstin": retailer.gstin or "",
                    "state_code": retailer.state_id,
                    "billing_address": address,
                    "shipping_address": address,
                },
                address=address,
                weight=1 / (rank + 3) ** 0.9,
                from_day=start
                if rng.random() < 0.75
                else start + timedelta(days=rng.randint(0, max((today - start).days - 5, 0))),
                mode=rng.choices(MODES, MODE_WEIGHTS)[0],
            )
        )
    return shops


# --- Bulk inserts --------------------------------------------------------------------------------

BACKDATED = (
    StockInward,
    StockInwardLine,
    Order,
    OrderLine,
    OrderStatusHistory,
    Fulfilment,
    FulfilmentLine,
    Invoice,
    InvoiceLine,
    CreditNote,
    CreditNoteLine,
    Payment,
    Allocation,
    LedgerEntry,
    StockMovement,
    DocumentSeries,
)


def _chunks[T](rows: list[T], size: int = BATCH) -> Iterator[list[T]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def _bulk(model: type[models.Model], rows: Iterable[models.Model]) -> int:
    made = model.objects.bulk_create(list(rows), batch_size=BATCH)  # type: ignore[attr-defined]
    return len(made)


def _stamp(when: datetime, updated: datetime | None = None) -> dict[str, datetime]:
    return {"created_at": when, "updated_at": updated or when}


def _series(sim: Simulation, t: UUID) -> None:
    _bulk(
        DocumentSeries,
        (
            DocumentSeries(
                id=pk,
                tenant_id=t,
                document_type=kind,
                fy=fy,
                prefix=sim.prefix(kind),
                padding=6,
                next_number=sim.numbers[(kind, fy)] + 1,
                **_stamp(sim.now),
            )
            for (kind, fy), pk in sim.series.items()
        ),
    )


def _inwards(sim: Simulation, t: UUID) -> None:
    by = sim.staff["WAREHOUSE"]
    heads, lines = [], []
    for inward_id, number, when, received in sim.inwards:
        total = sum((stock_value(q, i.cost) for i, q in received), ZERO)
        heads.append(
            StockInward(
                id=inward_id,
                tenant_id=t,
                number=number,
                warehouse_id=sim.warehouse_id,
                supplier_name="Main supplier",
                status=StockInward.Status.DRAFT,  # posted once its lines are in
                posted_at=when,
                posted_by_id=by,
                total_cost=total,
                cost_pending_lines=0,
                created_by_id=by,
                **_stamp(when),
            )
        )
        for no, (item, qty) in enumerate(received, 1):
            lines.append(
                StockInwardLine(
                    tenant_id=t,
                    inward_id=inward_id,
                    line_no=no,
                    product_id=item.id,
                    entered_qty=qty,
                    quantity=qty,
                    entered_cost=item.cost,
                    unit_cost=item.cost,
                    line_cost=stock_value(qty, item.cost),
                    cost_status="SET",
                    created_by_id=by,
                    **_stamp(when),
                )
            )
    _bulk(StockInward, heads)
    for chunk in _chunks(lines):
        _bulk(StockInwardLine, chunk)
    # Posted like ``receipts.post``: a posted receipt's lines can't be added (database trigger).
    StockInward.objects.filter(pk__in=[h.pk for h in heads]).update(
        status=StockInward.Status.POSTED
    )


def _order_rows(sim: Simulation, t: UUID, chunk: list[Ord]) -> None:
    orders, lines, steps, ships, ship_lines, bills, bill_lines = [], [], [], [], [], [], []
    for o in chunk:
        tt = o.totals
        orders.append(
            Order(
                id=o.id,
                tenant_id=t,
                number=o.number,
                retailer_id=o.shop.id,
                placed_by_id=o.placed_by,
                placed_via=o.via,
                placed_by_label=o.label,
                salesperson_id=o.shop.salesperson_id,
                status=o.status,
                backorder_state=o.backorder_state,
                hold_reason=o.hold_reason,
                settings_snapshot=sim.order_snapshot,
                shipping_address=o.shop.address,
                billing_address=o.shop.address,
                place_of_supply_id=o.shop.state,
                supply_type=o.shop.supply.value,
                prices_include_tax=False,
                gross_total=sum((ln.tax.gross_excl for ln in o.lines), ZERO),
                discount_total=ZERO,
                taxable_total=tt.taxable,
                tax_total=tt.cgst + tt.sgst + tt.igst + tt.cess,
                round_off=tt.round_off,
                grand_total=tt.grand_total,
                placed_at=o.placed_at,
                accepted_at=o.accepted_at,
                accepted_by_id=o.accepted_by,
                closed_at=o.closed_at,
                rejection_reason=o.reason if o.status == OrderStatus.REJECTED else "",
                cancellation_reason=o.reason if o.status == OrderStatus.CANCELLED else "",
                cancelled_by_id=o.cancelled_by,
                created_by_id=o.placed_by,
                **_stamp(o.placed_at, o.updated_at),
            )
        )
        for ln in o.lines:
            i = ln.item
            lines.append(
                OrderLine(
                    id=ln.id,
                    tenant_id=t,
                    order_id=o.id,
                    line_no=ln.no,
                    product_id=i.id,
                    product_code=i.code,
                    product_name=i.name,
                    hsn_code=i.hsn,
                    unit_code=i.unit,
                    base_price=i.price,
                    unit_price=i.price,
                    price_source="BASE",
                    gst_rate=i.rate,
                    qty_ordered=ln.qty,
                    qty_reserved=ln.reserved,
                    qty_backordered=ln.backordered,
                    qty_allocated=ln.allocated,
                    qty_cancelled=ln.cancelled,
                    qty_dispatched=ln.dispatched,
                    qty_delivered=ln.delivered,
                    qty_invoiced=ln.invoiced,
                    gross_amount=ln.tax.gross,
                    discount_amount=ZERO,
                    taxable_amount=ln.tax.taxable,
                    tax_amount=ln.tax.tax,
                    line_total=ln.tax.line_total,
                    created_by_id=o.placed_by,
                    **_stamp(o.placed_at, o.updated_at),
                )
            )
        for s in o.history:
            steps.append(
                OrderStatusHistory(
                    tenant_id=t,
                    order_id=o.id,
                    from_status=s.from_status,
                    to_status=s.to_status,
                    event=s.event,
                    actor_id=s.actor,
                    actor_type=s.actor_type,
                    **_stamp(s.at),
                )
            )
        ship = o.shipment
        if ship is None:
            continue
        last = ship.delivered_at or ship.dispatched_at or ship.packed_at or ship.created_at
        ships.append(
            Fulfilment(
                id=ship.id,
                tenant_id=t,
                order_id=o.id,
                number=ship.number,
                kind=Fulfilment.Kind.INITIAL,
                status=ship.status,
                warehouse_id=sim.warehouse_id,
                packed_at=ship.packed_at,
                dispatched_at=ship.dispatched_at,
                delivered_at=ship.delivered_at,
                created_by_id=o.accepted_by,
                **_stamp(ship.created_at, last),
            )
        )
        for sl_id, ln, qty in ship.lines:
            ship_lines.append(
                FulfilmentLine(
                    id=sl_id,
                    tenant_id=t,
                    fulfilment_id=ship.id,
                    order_line_id=ln.id,
                    product_id=ln.item.id,
                    quantity=qty,
                    qty_packed=qty if ship.packed_at else None,
                    unit_price=ln.item.price,
                    created_by_id=o.accepted_by,
                    **_stamp(ship.created_at, last),
                )
            )
        bill = sim.bill_of_ship.get(ship.id)
        if bill is None:
            continue
        tt = bill.totals
        status = (
            PaymentStatus.PAID
            if bill.balance == 0
            else PaymentStatus.PARTIAL
            if bill.paid + bill.credited > 0
            else PaymentStatus.UNPAID
        )
        bills.append(
            Invoice(
                id=bill.id,
                tenant_id=t,
                number=bill.number,
                series_id=bill.series_id,
                fy=bill.fy,
                retailer_id=o.shop.id,
                seller=sim.seller,
                buyer=o.shop.buyer,
                place_of_supply_id=o.shop.state,
                supply_type=o.shop.supply.value,
                prices_include_tax=False,
                settings_snapshot=sim.rounding_snapshot,
                gross_total=sum((bl.tax.gross_excl for bl in bill.lines), ZERO),
                discount_total=ZERO,
                taxable_total=tt.taxable,
                cgst_total=tt.cgst,
                sgst_total=tt.sgst,
                igst_total=tt.igst,
                cess_total=tt.cess,
                round_off=tt.round_off,
                grand_total=tt.grand_total,
                amount_in_words=amount_in_words(tt.grand_total),
                issued_by_id=bill.by,
                invoice_date=bill.day,
                due_date=bill.due,
                order_id=o.id,
                fulfilment_id=ship.id,
                issued_trigger=Invoice.Trigger.ON_DISPATCH,
                amount_paid=bill.paid,
                amount_credited=bill.credited,
                balance_due=bill.balance,
                payment_status=status,
                created_by_id=bill.by,
                **_stamp(bill.created_at, bill.updated_at),
            )
        )
        for bl in bill.lines:
            x, i = bl.tax, bl.line.item
            bill_lines.append(
                InvoiceLine(
                    id=bl.id,
                    tenant_id=t,
                    invoice_id=bill.id,
                    line_no=bl.no,
                    order_line_id=bl.line.id,
                    fulfilment_line_id=bl.ship_line_id,
                    product_id=i.id,
                    description=i.name,
                    product_code=i.code,
                    hsn_code=i.hsn,
                    unit_code=i.unit,
                    quantity=bl.qty,
                    unit_price=i.price,
                    gross_amount=x.gross_excl,
                    discount_amount=x.discount_excl,
                    taxable_value=x.taxable,
                    gst_rate=i.rate,
                    cgst_rate=x.cgst_rate,
                    cgst_amount=x.cgst,
                    sgst_rate=x.sgst_rate,
                    sgst_amount=x.sgst,
                    igst_rate=x.igst_rate,
                    igst_amount=x.igst,
                    cess_rate=x.cess_rate,
                    cess_amount=x.cess,
                    line_total=x.line_total,
                    order_rate=i.rate,
                    unit_cost=bl.unit_cost,
                    created_by_id=bill.by,
                    **_stamp(bill.created_at),
                )
            )
    _bulk(Order, orders)
    _bulk(OrderLine, lines)
    _bulk(OrderStatusHistory, steps)
    _bulk(Fulfilment, ships)
    _bulk(FulfilmentLine, ship_lines)
    _bulk(Invoice, bills)
    _bulk(InvoiceLine, bill_lines)


def _note_rows(sim: Simulation, t: UUID) -> None:
    notes, lines = [], []
    for n in sim.notes:
        tt, c, shop = n.totals, n.credit, n.bill.order.shop
        notes.append(
            CreditNote(
                id=n.id,
                tenant_id=t,
                number=n.number,
                series_id=n.series_id,
                fy=n.fy,
                retailer_id=shop.id,
                seller=sim.seller,
                buyer=shop.buyer,
                place_of_supply_id=shop.state,
                supply_type=shop.supply.value,
                prices_include_tax=False,
                settings_snapshot=sim.rounding_snapshot,
                gross_total=tt.taxable,
                taxable_total=tt.taxable,
                cgst_total=tt.cgst,
                sgst_total=tt.sgst,
                igst_total=tt.igst,
                cess_total=tt.cess,
                round_off=tt.round_off,
                grand_total=tt.grand_total,
                amount_in_words=amount_in_words(tt.grand_total),
                issued_by_id=n.by,
                note_date=n.day,
                invoice_id=n.bill.id,
                kind=CreditNote.Kind.RETURN,
                return_reason=n.reason,
                applied_to_invoice=n.applied,
                unapplied_amount=n.unapplied,
                created_by_id=n.by,
                **_stamp(n.created_at),
            )
        )
        lines.append(
            CreditNoteLine(
                tenant_id=t,
                credit_note_id=n.id,
                line_no=1,
                invoice_line_id=n.part.id,
                quantity=n.qty,
                disposition=CreditNoteLine.Disposition.RETURN_TO_STOCK,
                taxable_value=c.taxable,
                cgst_amount=c.cgst,
                sgst_amount=c.sgst,
                igst_amount=c.igst,
                cess_amount=c.cess,
                line_total=c.total,
                created_by_id=n.by,
                **_stamp(n.created_at),
            )
        )
    _bulk(CreditNote, notes)
    _bulk(CreditNoteLine, lines)


def _payment_rows(sim: Simulation, t: UUID) -> None:
    rows = []
    for r in sim.receipts:
        handed = sim.handovers.get(r.id)
        cleared = sim.cleared.get(r.id)
        cheque = r.mode == "CHEQUE"
        handover = (
            Payment.Handover.NOT_TRACKED
            if r.collected_by is None
            else Payment.Handover.HANDED_OVER
            if handed
            else Payment.Handover.WITH_SALESMAN
        )
        rows.append(
            Payment(
                id=r.id,
                tenant_id=t,
                number=r.number,
                retailer_id=r.shop.id,
                amount=r.amount,
                mode=r.mode,
                status=Payment.Status.CLEARED if cleared else Payment.Status.RECEIVED,
                credit_timing=Payment.CreditTiming.ON_RECEIPT,
                payment_date=r.day,
                reference_no="" if r.mode in ("CASH", "CHEQUE") else f"UTR{r.seq:012d}",
                cheque_number=f"{r.seq % 1_000_000:06d}" if cheque else "",
                cheque_date=r.day if cheque else None,
                bank_name="State Bank" if cheque else "",
                recorded_by_id=r.recorded_by,
                collected_by_id=r.collected_by,
                handover_status=handover,
                handed_over_at=handed,
                handed_over_by_id=sim.staff["ACCOUNTS"] if handed else None,
                credited=True,
                cleared_at=cleared,
                unapplied_amount=r.unapplied,
                created_by_id=r.recorded_by,
                **_stamp(r.created_at, max(filter(None, (r.created_at, handed, cleared)))),
            )
        )
    for chunk in _chunks(rows):
        _bulk(Payment, chunk)


def _money_rows(sim: Simulation, t: UUID) -> None:
    for allocations in _chunks(sim.allocations):
        _bulk(
            Allocation,
            (
                Allocation(tenant_id=t, automatic=True, updated_at=a.created_at, **a._asdict())
                for a in allocations
            ),
        )
    for entries in _chunks(sim.ledger):
        _bulk(
            LedgerEntry,
            (LedgerEntry(tenant_id=t, updated_at=e.created_at, **e._asdict()) for e in entries),
        )


def _movement_rows(sim: Simulation, t: UUID) -> None:
    for movements in _chunks(sim.movements):
        _bulk(
            StockMovement,
            (
                StockMovement(
                    tenant_id=t,
                    warehouse_id=sim.warehouse_id,
                    updated_at=m.created_at,
                    **m._asdict(),
                )
                for m in movements
            ),
        )


def _finish(sim: Simulation) -> None:
    """Counters, stock levels and shop accounts as the simulation left them."""
    for (name, period), used in sim.numbers.items():
        if name in ("ORDER", "GRN"):
            Sequence.objects.update_or_create(
                name=name, period=period, defaults={"next_value": used + 1}
            )
    from apps.inventory.services import ensure_levels_exist

    warehouse = Warehouse.objects.get(pk=sim.warehouse_id)
    ensure_levels_exist([i.id for i in sim.items], warehouse)
    levels = {lv.product_id: lv for lv in StockLevel.objects.filter(warehouse=warehouse)}
    for item in sim.items:
        level = levels[item.id]
        level.quantity_on_hand, level.quantity_reserved = item.on_hand, item.reserved
        level.quantity_backordered = item.backordered
    StockLevel.objects.bulk_update(
        list(levels.values()),
        ["quantity_on_hand", "quantity_reserved", "quantity_backordered"],
        batch_size=BATCH,
    )
    accounts = {a.retailer_id: a for a in RetailerAccount.objects.all()}
    for shop in sim.shops:
        account = accounts[shop.id]
        account.balance, account.total_debits = shop.balance, shop.debits
        account.total_credits, account.unapplied_credit = shop.credits, shop.unapplied
        account.last_entry_at = shop.last_entry_at
    RetailerAccount.objects.bulk_update(
        list(accounts.values()),
        ["balance", "total_debits", "total_credits", "unapplied_credit", "last_entry_at"],
        batch_size=BATCH,
    )


def insert(sim: Simulation) -> Result:
    t = sim.tenant.pk
    with backdated(*BACKDATED):
        _series(sim, t)
        _inwards(sim, t)
        for chunk in _chunks(sim.orders, 1000):
            _order_rows(sim, t, chunk)
        _note_rows(sim, t)
        _payment_rows(sim, t)
        _money_rows(sim, t)
        _movement_rows(sim, t)
    _finish(sim)
    return Result(
        orders=len(sim.orders),
        invoices=len(sim.bills),
        credit_notes=len(sim.notes),
        payments=len(sim.receipts),
        movements=len(sim.movements),
        ledger_entries=len(sim.ledger),
    )


def seed_tenant(
    spec: VolumeTenant,
    *,
    days: int = 365,
    seed: int = 8,
    progress: Callable[[str], None] = lambda _message: None,
) -> Result | None:
    """One test distributor and its year (inside the caller's transaction). ``None`` when it
    already has orders: run it on a fresh database, or after removing the distributor."""
    rng = random.Random(f"{spec.slug}:{seed}")  # noqa: S311 - demo data, not security
    tenant = setup_tenant(spec)
    with tenant_context(tenant.pk):
        if Order.objects.exists():
            return None
        today = today_ist()
        start = today - timedelta(days=days)
        staff, salespeople = setup_staff(spec)
        owner = User.objects.get(pk=staff["OWNER"])
        progress(f"{spec.slug}: {spec.products} products")
        items = setup_items(tenant, spec, owner, rng, start, today)
        progress(f"{spec.slug}: {spec.shops} shops")
        shops = setup_shops(tenant, spec, owner, salespeople, rng, start, today)
        progress(f"{spec.slug}: simulating {spec.orders} orders over {days} days")
        sim = Simulation(
            tenant,
            spec,
            items=items,
            shops=shops,
            staff=staff,
            salespeople=salespeople,
            warehouse_id=ensure_default_warehouse(Warehouse).pk,
            days=days,
            rng=rng,
        )
        sim.run()
        progress(f"{spec.slug}: inserting")
        return insert(sim)


# --- Reconciliation ------------------------------------------------------------------------------


def _sums(qs: Any, key: str, value: str) -> dict[Any, Decimal]:
    return {
        k: v or ZERO
        for k, v in qs.values(key).annotate(s=Sum(value)).values_list(key, "s").order_by()
    }


def reconcile() -> list[str]:
    """What doesn't agree, for the active distributor (empty when everything does): accounts
    against their ledger, invoices, payments and credit notes against their allocations, invoice
    totals against their lines, stock levels against their movements, backorders against open
    order lines, and what was invoiced against the order lines."""
    problems: list[str] = []

    def differ(what: str, left: dict[Any, Decimal], right: dict[Any, Decimal]) -> None:
        bad = [k for k in set(left) | set(right) if left.get(k, ZERO) != right.get(k, ZERO)]
        if bad:
            problems.append(f"{what}: {len(bad)} differ, e.g. {bad[0]}")

    entries = LedgerEntry.objects.all()
    accounts = RetailerAccount.objects.all()
    differ(
        "account balance vs its ledger",
        dict(accounts.values_list("retailer_id", "balance")),
        {
            k: d - c
            for k, d, c in entries.values("retailer_id")
            .annotate(d=Sum("debit"), c=Sum("credit"))
            .values_list("retailer_id", "d", "c")
            .order_by()
        },
    )
    last = dict(
        entries.order_by("retailer_id", "-created_at", "-id")
        .distinct("retailer_id")
        .values_list("retailer_id", "balance_after")
    )
    differ(
        "account balance vs its last entry",
        dict(accounts.values_list("retailer_id", "balance")),
        last,
    )
    live = Allocation.objects.filter(amount__gt=0, reversed_by__isnull=True)
    invoices = Invoice.objects.filter(status="ISSUED")
    differ(
        "invoice paid vs payment allocations",
        dict(invoices.values_list("id", "amount_paid")),
        _sums(live.filter(payment__isnull=False), "invoice_id", "amount"),
    )
    differ(
        "invoice credited vs credit note allocations",
        dict(invoices.values_list("id", "amount_credited")),
        _sums(live.filter(credit_note__isnull=False), "invoice_id", "amount"),
    )
    wrong_balance = invoices.exclude(
        balance_due=F("grand_total") - F("amount_paid") - F("amount_credited")
    ).count()
    if wrong_balance:
        problems.append(f"invoice balance vs total - paid - credited: {wrong_balance} differ")
    payments = Payment.objects.filter(credited=True)
    differ(
        "payment unused vs amount - allocations",
        dict(payments.values_list("id", "unapplied_amount")),
        {
            pk: amount - (used or ZERO)
            for pk, amount, used in payments.annotate(used=Sum("allocations__amount")).values_list(
                "id", "amount", "used"
            )
        },
    )
    differ(
        "invoice total vs its lines and round-off",
        dict(invoices.values_list("id", "grand_total")),
        {
            pk: (lines or ZERO) + round_off
            for pk, lines, round_off in invoices.annotate(
                lines_total=Sum("lines__line_total")
            ).values_list("id", "lines_total", "round_off")
        },
    )
    unused = sum(payments.values_list("unapplied_amount", flat=True), ZERO) + sum(
        CreditNote.objects.values_list("unapplied_amount", flat=True), ZERO
    )
    held = sum(accounts.values_list("unapplied_credit", flat=True), ZERO)
    if unused != held:
        problems.append(f"unused money {unused} vs the accounts' unused credit {held}")
    owed = (
        sum(invoices.values_list("grand_total", flat=True), ZERO)
        - sum(CreditNote.objects.values_list("grand_total", flat=True), ZERO)
        - sum(payments.values_list("amount", flat=True), ZERO)
    )
    balances = sum(accounts.values_list("balance", flat=True), ZERO)
    if owed != balances:
        problems.append(f"invoices - credit notes - payments {owed} vs account balances {balances}")
    movements = StockMovement.objects.all()
    levels = StockLevel.objects.all()
    differ(
        "stock on hand vs movements",
        dict(levels.values_list("product_id", "quantity_on_hand")),
        _sums(movements, "product_id", "delta_on_hand"),
    )
    differ(
        "stock reserved vs movements",
        dict(levels.values_list("product_id", "quantity_reserved")),
        _sums(movements, "product_id", "delta_reserved"),
    )
    newest = movements.order_by("product_id", "-created_at", "-id").distinct("product_id")
    differ(
        "stock on hand vs its last movement",
        dict(levels.values_list("product_id", "quantity_on_hand")),
        dict(newest.values_list("product_id", "on_hand_after")),
    )
    differ(
        "stock reserved vs its last movement",
        dict(levels.values_list("product_id", "quantity_reserved")),
        dict(newest.values_list("product_id", "reserved_after")),
    )
    from apps.orders.models import OPEN_STATUSES

    differ(
        "stock backordered vs open order lines",
        dict(levels.values_list("product_id", "quantity_backordered")),
        _sums(
            OrderLine.objects.filter(order__status__in=OPEN_STATUSES, qty_backordered__gt=0),
            "product_id",
            "qty_backordered",
        ),
    )
    differ(
        "order line invoiced vs invoice lines",
        {k: v for k, v in OrderLine.objects.values_list("id", "qty_invoiced") if v},
        _sums(InvoiceLine.objects.filter(invoice__status="ISSUED"), "order_line_id", "quantity"),
    )
    return problems
