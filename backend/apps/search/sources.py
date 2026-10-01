"""What global search looks in (ADR-053): one source per kind of record, each with the permission
its own list needs and the same visibility rules (the sales-visibility rule through the existing
``*_for(user)`` selectors). A source finds records for typed text, and some also name the one
record a typed number, GSTIN, mobile or barcode refers to.

Results carry no cost data: goods receipts give their supplier and date, never their total cost.
Titles and details are the records' own words (names, numbers, codes); the app adds its words."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import Case, IntegerField, Q, QuerySet, Value, When

from apps.accounts.models import Membership, User
from apps.billing.selectors import credit_notes_for, invoices_for
from apps.catalog.models import Product, ProductBarcode
from apps.catalog.search import ranked_queryset
from apps.inventory.models import StockAdjustment, StockInward
from apps.orders.selectors import orders_for
from apps.payments.selectors import payments_for, refunds_for
from apps.retailers.selectors import retailers_for
from common.dates import to_ist
from common.permissions import AnyOf, Requirement

# What a typed text may be, to jump straight to its record.
ORDER_NUMBER = re.compile(r"ORD-(\d{4})-(\d{1,8})(?:/\d+)?", re.IGNORECASE)  # an order or shipment
# Invoices, credit notes, receipts and refunds: PREFIX/YY-YY/NUMBER, prefixes set per distributor.
SERIES_NUMBER = re.compile(r"([A-Z0-9-]{1,8})/(\d{2}-\d{2})/(\d{1,8})", re.IGNORECASE)
GRN_NUMBER = re.compile(r"GRN-(\d{4})-(\d{1,8})", re.IGNORECASE)
ADJ_NUMBER = re.compile(r"ADJ-(\d{4})-(\d{1,8})", re.IGNORECASE)
GSTIN = re.compile(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]")
BARCODE = re.compile(r"\d{8,14}")


@dataclass(frozen=True)
class Hit:
    type: str
    id: UUID
    title: str
    detail: str = ""
    date: date | None = None
    amount: Decimal | None = None
    status: str = ""


@dataclass(frozen=True)
class Source:
    type: str
    requirement: Requirement
    find: Callable[[User, str, int], list[Hit]]
    exact: Callable[[User, str], list[Hit]] | None = None
    # Only searched when the text has a digit: these are found by their numbers.
    numbers_only: bool = False
    feature: str = ""  # an optional module that must be on (e.g. purchasing)


def mobile_of(text: str) -> str | None:
    """A 10-digit Indian mobile in any common spelling (+91, 0, spaces, dashes) as stored."""
    digits = re.sub(r"\D", "", text)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789" and re.fullmatch(r"[\d\s()+-]+", text):
        return f"+91{digits}"
    return None


def _number_pattern(prefix: str, number: str) -> str:
    """A regular expression for a document number typed without its zero padding."""
    return rf"^{re.escape(prefix)}0*{int(number)}$"


def _first_exact(qs: QuerySet[Any], text: str) -> QuerySet[Any]:
    """Exact number matches first, then the newest."""
    first: QuerySet[Any] = qs.annotate(
        exact=Case(
            When(number__iexact=text, then=Value(0)), default=Value(1), output_field=IntegerField()
        )
    )
    return first


# --- Products and shops ---------------------------------------------------------------------------


def _products(user: User, text: str, limit: int) -> list[Hit]:
    found = ranked_queryset(Product.objects.filter(deleted_at__isnull=True), text)
    return [
        Hit("product", p.pk, p.name, p.code, status="ACTIVE" if p.is_active else "INACTIVE")
        for p in found.only("id", "name", "code", "is_active")[:limit]
    ]


def _product_exact(user: User, text: str) -> list[Hit]:
    if not BARCODE.fullmatch(text):
        return []
    found = Product.objects.filter(
        deleted_at__isnull=True,
        pk__in=ProductBarcode.objects.filter(barcode=text).values("product_id"),
    )
    return [Hit("product", p.pk, p.name, p.code) for p in found[:2]]


def _shop_hit(r: Any) -> Hit:
    return Hit(
        "shop",
        r.pk,
        r.shop_name,
        " · ".join(x for x in (r.code, r.owner_name) if x),
        status=r.status,
    )


def _shops(user: User, text: str, limit: int) -> list[Hit]:
    digits = re.sub(r"\D", "", text)
    condition = (
        Q(shop_name__icontains=text)
        | Q(owner_name__icontains=text)
        | Q(code__iexact=text)
        | Q(shop_name__trigram_word_similar=text)
    )
    if len(digits) >= 4:
        condition |= Q(mobile__contains=digits)
    if len(text) >= 5 and re.fullmatch(r"[0-9A-Za-z]+", text):
        condition |= Q(gstin__icontains=text.upper())
    found = (
        retailers_for(user)
        .select_related(None)
        .filter(condition)
        .annotate(similarity=TrigramWordSimilarity(text, "shop_name"))
        .order_by("-similarity", "shop_name")
    )
    return [_shop_hit(r) for r in found[:limit]]


def _shop_exact(user: User, text: str) -> list[Hit]:
    upper = text.upper().replace(" ", "")
    if GSTIN.fullmatch(upper):
        return [_shop_hit(r) for r in retailers_for(user).filter(gstin=upper)[:2]]
    mobile = mobile_of(text)
    if mobile:
        return [_shop_hit(r) for r in retailers_for(user).filter(mobile=mobile)[:2]]
    return []


# --- Orders and money documents ----------------------------------------------------------------


def _order_hit(o: Any) -> Hit:
    return Hit(
        "order",
        o.pk,
        o.number,
        o.retailer.shop_name,
        date=to_ist(o.placed_at).date(),
        amount=o.grand_total,
        status=o.status,
    )


def _orders(user: User, text: str, limit: int) -> list[Hit]:
    found = _first_exact(orders_for(user).filter(number__icontains=text), text)
    return [
        _order_hit(o)
        for o in found.select_related("retailer").order_by("exact", "-placed_at")[:limit]
    ]


def _order_exact(user: User, text: str) -> list[Hit]:
    match = ORDER_NUMBER.fullmatch(text)
    if not match:
        return []
    year, number = match.groups()
    pattern = _number_pattern(f"ORD-{year}-", number)
    found = orders_for(user).filter(number__iregex=pattern).select_related("retailer")
    return [_order_hit(o) for o in found[:2]]


def _document(kind: str, day: str, total: str, status: str) -> Callable[[Any], Hit]:
    def hit(d: Any) -> Hit:
        return Hit(
            kind,
            d.pk,
            d.number,
            d.retailer.shop_name,
            date=getattr(d, day),
            amount=getattr(d, total),
            status=getattr(d, status),
        )

    return hit


INVOICE_HIT = _document("invoice", "invoice_date", "grand_total", "payment_status")
CREDIT_NOTE_HIT = _document("credit_note", "note_date", "grand_total", "status")
PAYMENT_HIT = _document("payment", "payment_date", "amount", "status")
REFUND_HIT = _document("refund", "refund_date", "amount", "status")


def _by_number(
    queryset: Callable[[User], QuerySet[Any]], hit: Callable[[Any], Hit], day: str
) -> Callable[[User, str, int], list[Hit]]:
    def find(user: User, text: str, limit: int) -> list[Hit]:
        found = _first_exact(queryset(user).filter(number__icontains=text), text)
        return [
            hit(d) for d in found.select_related("retailer").order_by("exact", f"-{day}")[:limit]
        ]

    return find


def _series_exact(
    queryset: Callable[[User], QuerySet[Any]], hit: Callable[[Any], Hit]
) -> Callable[[User, str], list[Hit]]:
    def exact(user: User, text: str) -> list[Hit]:
        match = SERIES_NUMBER.fullmatch(text)
        if not match:
            return []
        prefix, fy, number = match.groups()
        pattern = _number_pattern(f"{prefix}/{fy}/", number)
        found = queryset(user).filter(number__iregex=pattern).select_related("retailer")
        return [hit(d) for d in found[:2]]

    return exact


def _payments(user: User, text: str, limit: int) -> list[Hit]:
    condition = Q(number__icontains=text) | Q(reference_no__icontains=text)
    condition |= Q(cheque_number__icontains=text)
    found = _first_exact(payments_for(user).filter(condition), text)
    return [
        PAYMENT_HIT(p)
        for p in found.select_related("retailer").order_by("exact", "-payment_date")[:limit]
    ]


# --- Stock documents and staff -------------------------------------------------------------------


def _receipt_hit(r: StockInward) -> Hit:
    # A draft has no number yet (the app calls it a draft); never the receipt's cost.
    when = r.bill_date or to_ist(r.posted_at or r.created_at).date()
    return Hit("goods_receipt", r.pk, r.number or "", r.supplier_name, date=when, status=r.status)


def _receipts(user: User, text: str, limit: int) -> list[Hit]:
    condition = (
        Q(number__icontains=text)
        | Q(supplier_name__icontains=text)
        | Q(bill_number__icontains=text)
    )
    found = StockInward.objects.filter(condition).only(
        "id", "number", "supplier_name", "bill_date", "posted_at", "created_at", "status"
    )
    return [_receipt_hit(r) for r in found.order_by("-created_at")[:limit]]


def _receipt_exact(user: User, text: str) -> list[Hit]:
    match = GRN_NUMBER.fullmatch(text)
    if not match:
        return []
    year, number = match.groups()
    found = StockInward.objects.filter(number__iregex=_number_pattern(f"GRN-{year}-", number))
    return [_receipt_hit(r) for r in found[:2]]


def _adjustment_hit(a: StockAdjustment) -> Hit:
    # The reason is a code the app words; the detail is the staff's own note.
    return Hit(
        "adjustment",
        a.pk,
        a.number,
        a.note[:80],
        date=to_ist(a.created_at).date(),
        status=a.reason_code,
    )


def _adjustments(user: User, text: str, limit: int) -> list[Hit]:
    found = _first_exact(StockAdjustment.objects.filter(number__icontains=text), text)
    return [_adjustment_hit(a) for a in found.order_by("exact", "-created_at")[:limit]]


def _adjustment_exact(user: User, text: str) -> list[Hit]:
    match = ADJ_NUMBER.fullmatch(text)
    if not match:
        return []
    year, number = match.groups()
    found = StockAdjustment.objects.filter(number__iregex=_number_pattern(f"ADJ-{year}-", number))
    return [_adjustment_hit(a) for a in found[:2]]


def _staff(user: User, text: str, limit: int) -> list[Hit]:
    found = (
        Membership.objects.filter(
            Q(user__full_name__icontains=text) | Q(user__email__icontains=text)
        )
        .select_related("user", "role")
        .order_by("user__full_name", "pk")
    )
    return [
        Hit(
            "staff",
            m.pk,
            m.user.full_name or m.user.email,
            m.user.email,
            status="ACTIVE" if m.is_active else "INACTIVE",
        )
        for m in found[:limit]
    ]


def _supplier_hit(supplier: Any) -> Hit:
    detail = " · ".join(x for x in (supplier.code, supplier.city) if x)
    return Hit(
        "supplier",
        supplier.pk,
        supplier.name,
        detail,
        status="ACTIVE" if supplier.is_active else "INACTIVE",
    )


def _suppliers(user: User, text: str, limit: int) -> list[Hit]:
    from apps.purchasing.selectors import suppliers

    return [_supplier_hit(s) for s in suppliers(search=text)[:limit]]


def _supplier_exact(user: User, text: str) -> list[Hit]:
    from apps.purchasing.models import Supplier

    gstin = text.upper().replace(" ", "")
    if not GSTIN.fullmatch(gstin):
        return []
    found = Supplier.objects.filter(gstin=gstin, deleted_at__isnull=True)
    return [_supplier_hit(s) for s in found[:2]]


SOURCES: tuple[Source, ...] = (
    Source("product", "products.view", _products, _product_exact),
    Source("shop", "retailers.view", _shops, _shop_exact),
    Source("order", "orders.view", _orders, _order_exact, numbers_only=True),
    Source(
        "invoice",
        "invoices.view",
        _by_number(invoices_for, INVOICE_HIT, "invoice_date"),
        _series_exact(invoices_for, INVOICE_HIT),
        numbers_only=True,
    ),
    Source(
        "credit_note",
        "invoices.view",
        _by_number(credit_notes_for, CREDIT_NOTE_HIT, "note_date"),
        _series_exact(credit_notes_for, CREDIT_NOTE_HIT),
        numbers_only=True,
    ),
    Source(
        "payment",
        "payments.view",
        _payments,
        _series_exact(payments_for, PAYMENT_HIT),
        numbers_only=True,
    ),
    Source(
        "refund",
        "payments.view",
        _by_number(refunds_for, REFUND_HIT, "refund_date"),
        _series_exact(refunds_for, REFUND_HIT),
        numbers_only=True,
    ),
    Source("goods_receipt", AnyOf(("stock.inward", "costs.view")), _receipts, _receipt_exact),
    Source("adjustment", "stock.adjust", _adjustments, _adjustment_exact, numbers_only=True),
    Source("staff", "staff.manage", _staff),
    Source("supplier", "purchasing.view", _suppliers, _supplier_exact, feature="purchasing"),
)
TYPES = tuple(source.type for source in SOURCES)
