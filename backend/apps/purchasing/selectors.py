"""Purchasing reads."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import Count, F, Min, Q, QuerySet, Sum
from django.db.models.functions import Greatest

from apps.inventory.models import StockInward
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Supplier, SupplierProduct
from common.dates import to_ist, today_ist
from common.search_keys import key

OPEN_STATUSES = (PurchaseOrder.Status.SENT, PurchaseOrder.Status.PARTLY_RECEIVED)


def suppliers(*, search: str = "", active: bool | None = None) -> QuerySet[Supplier]:
    qs = Supplier.objects.filter(deleted_at__isnull=True).select_related("state")
    if active is not None:
        qs = qs.filter(is_active=active)
    term = " ".join(search.split())[:100]
    if term:
        in_letters = key(term)  # in either script (ADR-060 item 8)
        qs = (
            qs.filter(
                Q(name__icontains=term)
                | Q(code__iexact=term)
                | Q(gstin__iexact=term.upper())
                | Q(contact_name__icontains=term)
                | Q(name__trigram_word_similar=term)
                | Q(name_key__trigram_word_similar=in_letters)
            )
            .annotate(
                similarity=Greatest(
                    TrigramWordSimilarity(term, "name"),
                    TrigramWordSimilarity(in_letters, "name_key"),
                )
            )
            .order_by("-similarity", "name", "id")
        )
    counted: QuerySet[Supplier] = qs.annotate(product_count=Count("links", distinct=True))
    return counted


def supplier(supplier_id: UUID) -> Supplier | None:
    found: Supplier | None = suppliers().filter(pk=supplier_id).first()
    return found


def product_suppliers(product_id: UUID) -> QuerySet[SupplierProduct]:
    return (
        SupplierProduct.objects.filter(product_id=product_id, supplier__deleted_at__isnull=True)
        .select_related("supplier")
        .order_by("-is_preferred", "supplier__name")
    )


# --- Suppliers from past goods receipts --------------------------------------------------------


def name_key(name: str) -> str:
    """Names that differ only in case or spacing are the same supplier."""
    return " ".join(name.split()).lower()


def unlinked_receipts() -> list[tuple[UUID, str]]:
    return list(
        StockInward.objects.filter(supplier__isnull=True)
        .exclude(supplier_name="")
        .values_list("pk", "supplier_name")
    )


@dataclass(frozen=True)
class ReceiptSupplierName:
    name: str  # the most used spelling (on a tie, the one with capitals)
    receipts: int
    last_date: date | None
    match_id: UUID | None  # a supplier with the same name, offered as the choice
    match_name: str


def receipt_supplier_names() -> list[ReceiptSupplierName]:
    """Supplier names typed on goods receipts that aren't linked to a supplier yet, with how many
    receipts each, newest first."""
    rows = (
        StockInward.objects.filter(supplier__isnull=True)
        .exclude(supplier_name="")
        .values_list("supplier_name", "bill_date", "posted_at", "created_at")
    )
    spellings: dict[str, Counter[str]] = defaultdict(Counter)
    last: dict[str, date] = {}
    for typed, bill_date, posted_at, created_at in rows:
        key = name_key(typed)
        spellings[key][" ".join(typed.split())] += 1
        when = bill_date or to_ist(posted_at or created_at).date()
        if key not in last or when > last[key]:
            last[key] = when
    existing: dict[str, Any] = {}
    for found in Supplier.objects.filter(deleted_at__isnull=True).only("id", "name"):
        existing.setdefault(name_key(found.name), found)
    out = [
        ReceiptSupplierName(
            name=min(counts, key=lambda typed: (-counts[typed], typed)),  # capitals first
            receipts=sum(counts.values()),
            last_date=last.get(key),
            match_id=existing[key].pk if key in existing else None,
            match_name=existing[key].name if key in existing else "",
        )
        for key, counts in spellings.items()
    ]
    out.sort(key=lambda r: (-(r.last_date or date.min).toordinal(), r.name.lower()))
    return out


def product_exists(product_id: UUID) -> bool:
    from apps.catalog.models import Product

    return Product.objects.filter(pk=product_id, deleted_at__isnull=True).exists()


# --- Purchase orders ------------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderFilters:
    status: str = ""
    supplier_id: UUID | None = None
    late: bool = False  # sent or partly received, expected before today
    search: str = ""


def purchase_orders(f: OrderFilters | None = None) -> QuerySet[PurchaseOrder]:
    f = f or OrderFilters()
    qs = PurchaseOrder.objects.select_related("supplier").annotate(
        line_count=Count("lines", distinct=True)
    )
    if f.status:
        qs = qs.filter(status=f.status)
    if f.supplier_id:
        qs = qs.filter(supplier_id=f.supplier_id)
    if f.late:
        qs = qs.filter(status__in=OPEN_STATUSES, expected_date__lt=today_ist())
    term = " ".join(f.search.split())[:100]
    if term:
        qs = qs.filter(Q(number__icontains=term) | Q(supplier__name__icontains=term))
    found: QuerySet[PurchaseOrder] = qs
    return found


def purchase_order(order_id: UUID) -> PurchaseOrder | None:
    found: PurchaseOrder | None = (
        purchase_orders()
        .prefetch_related("lines")
        .select_related("sent_by")
        .filter(pk=order_id)
        .first()
    )
    return found


def open_orders_for(supplier_id: UUID) -> int:
    return PurchaseOrder.objects.filter(
        supplier_id=supplier_id, status__in=(PurchaseOrder.Status.DRAFT, *OPEN_STATUSES)
    ).count()


# --- On order (ADR-053 item 7: quantities and dates, never suppliers or prices) ----------------


@dataclass(frozen=True)
class OnOrder:
    quantity: Decimal
    expected_date: date | None  # the earliest
    late: bool


def on_order(product_ids: list[UUID] | None = None) -> dict[UUID, OnOrder]:
    """What is still due on sent and partly received orders, per product."""
    lines = PurchaseOrderLine.objects.filter(order__status__in=OPEN_STATUSES)
    if product_ids is not None:
        lines = lines.filter(product_id__in=product_ids)
    rows = (
        lines.values("product_id")
        .annotate(
            due=Sum(F("quantity") - F("qty_received") - F("qty_cancelled")),
            expected=Min("order__expected_date"),
        )
        .order_by()
    )
    today = today_ist()
    out: dict[UUID, OnOrder] = {}
    for row in rows:
        due = max(row["due"] or Decimal("0"), Decimal("0"))
        if due > 0:
            expected = row["expected"]
            out[row["product_id"]] = OnOrder(due, expected, bool(expected and expected < today))
    return out


def on_order_detail(product_id: UUID) -> list[dict[str, Any]]:
    """Each open order's due quantity and expected date for one product, soonest first."""
    rows = (
        PurchaseOrderLine.objects.filter(order__status__in=OPEN_STATUSES, product_id=product_id)
        .values("order__expected_date")
        .annotate(due=Sum(F("quantity") - F("qty_received") - F("qty_cancelled")))
        .order_by(F("order__expected_date").asc(nulls_last=True))
    )
    today = today_ist()
    return [
        {
            "quantity": row["due"],
            "expected_date": row["order__expected_date"],
            "late": bool(row["order__expected_date"] and row["order__expected_date"] < today),
        }
        for row in rows
        if row["due"] and row["due"] > 0
    ]
