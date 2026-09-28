"""Invoice and credit-note reads (PLAN §3.10). Sales staff limited to their own shops
(⚙ orders.sales_visibility) see only those shops' documents."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import Prefetch, Q, QuerySet, Sum

from apps.accounts.models import User
from apps.billing.models import CreditNote, CreditNoteLine, Invoice, InvoiceLine
from apps.ledger.models import Allocation
from apps.ledger.selectors import applied_rows, used_for_rows
from apps.retailers.selectors import sees_own_retailers_only
from common.dates import today_ist


def _visible(qs: QuerySet[Any], user: User) -> QuerySet[Any]:
    return qs.filter(retailer__salesperson=user) if sees_own_retailers_only(user) else qs


@dataclass(frozen=True)
class InvoiceFilters:
    retailer_id: UUID | None = None
    payment_status: str = ""
    overdue: bool = False
    date_from: date | None = None
    date_to: date | None = None
    einvoice_status: str = ""
    search: str = ""


def invoices_for(user: User) -> QuerySet[Invoice]:
    return _visible(Invoice.objects.select_related("retailer", "order"), user)


def invoice_list(user: User, f: InvoiceFilters) -> QuerySet[Invoice]:
    qs = invoices_for(user)
    if f.retailer_id:
        qs = qs.filter(retailer_id=f.retailer_id)
    if f.payment_status:
        qs = qs.filter(payment_status=f.payment_status)
    if f.overdue:
        qs = qs.filter(balance_due__gt=0, due_date__lt=today_ist())
    if f.date_from:
        qs = qs.filter(invoice_date__gte=f.date_from)
    if f.date_to:
        qs = qs.filter(invoice_date__lte=f.date_to)
    if f.einvoice_status:
        qs = qs.filter(einvoice_status=f.einvoice_status)
    if f.search:
        term = f.search.strip()
        qs = qs.filter(
            Q(number__icontains=term)
            | Q(retailer__shop_name__icontains=term)
            | Q(retailer__code__iexact=term)
            | Q(order__number__icontains=term)
        )
    return qs


def invoice_detail(
    invoice_id: UUID, *, user: User | None = None, retailer_id: UUID | None = None
) -> Invoice | None:
    """For staff (``user``, with visibility) or for the shop itself (``retailer_id``)."""
    qs = invoices_for(user) if user is not None else Invoice.objects.filter(retailer_id=retailer_id)
    invoice: Invoice | None = (
        qs.select_related("retailer", "order", "place_of_supply", "fulfilment")
        .prefetch_related(
            Prefetch("lines", queryset=InvoiceLine.objects.order_by("line_no")),
            Prefetch("credit_notes", queryset=CreditNote.objects.order_by("created_at")),
        )
        .filter(pk=invoice_id)
        .first()
    )
    if invoice is None:
        return None
    credited = dict(
        CreditNoteLine.objects.filter(invoice_line__invoice=invoice)
        .values("invoice_line")
        .annotate(total=Sum("quantity"))
        .values_list("invoice_line", "total")
    )
    for line in invoice.lines.all():
        line.credited_quantity = Decimal(credited.get(line.pk) or 0)  # type: ignore[attr-defined]
    invoice.applied_rows = applied_rows(  # type: ignore[attr-defined]
        Allocation.objects.filter(invoice=invoice)
        .select_related("payment", "credit_note", "credit_adjustment")
        .order_by("created_at")
    )
    return invoice


@dataclass(frozen=True)
class CreditNoteFilters:
    retailer_id: UUID | None = None
    invoice_id: UUID | None = None
    kind: str = ""
    automatic: bool | None = None
    date_from: date | None = None
    date_to: date | None = None
    search: str = ""


def credit_notes_for(user: User) -> QuerySet[CreditNote]:
    return _visible(CreditNote.objects.select_related("retailer", "invoice"), user)


def credit_note_list(user: User, f: CreditNoteFilters) -> QuerySet[CreditNote]:
    qs = credit_notes_for(user)
    if f.retailer_id:
        qs = qs.filter(retailer_id=f.retailer_id)
    if f.invoice_id:
        qs = qs.filter(invoice_id=f.invoice_id)
    if f.kind:
        qs = qs.filter(kind=f.kind)
    if f.automatic is not None:
        qs = qs.filter(issued_automatically=f.automatic)
    if f.date_from:
        qs = qs.filter(note_date__gte=f.date_from)
    if f.date_to:
        qs = qs.filter(note_date__lte=f.date_to)
    if f.search:
        term = f.search.strip()
        qs = qs.filter(
            Q(number__icontains=term)
            | Q(invoice__number__icontains=term)
            | Q(retailer__shop_name__icontains=term)
        )
    return qs


def credit_note_detail(
    note_id: UUID, *, user: User | None = None, retailer_id: UUID | None = None
) -> CreditNote | None:
    qs = (
        credit_notes_for(user)
        if user is not None
        else CreditNote.objects.filter(retailer_id=retailer_id)
    )
    note: CreditNote | None = (
        qs.select_related("retailer", "invoice", "place_of_supply")
        .prefetch_related(
            Prefetch(
                "lines",
                queryset=CreditNoteLine.objects.select_related("invoice_line").order_by("line_no"),
            )
        )
        .filter(pk=note_id)
        .first()
    )
    if note is not None:
        note.used_for_rows = used_for_rows(  # type: ignore[attr-defined]
            Allocation.objects.filter(credit_note=note)
            .select_related("invoice", "debit_adjustment")
            .order_by("created_at")
        )
    return note
