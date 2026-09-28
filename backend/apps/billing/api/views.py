"""Invoices, credit notes and Order Confirmations for the distributor (PLAN §3.10). Thin:
permission → serializer → service/selector. Sales staff limited to their own shops get "not found"
for other shops' documents, as for another tenant's."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.billing import credit_notes, documents, numbering, selectors
from apps.billing.api import serializers as s
from apps.billing.credit_notes import ReturnLine
from apps.billing.models import (
    CreditNote,
    EInvoiceStatus,
    Invoice,
    OrderConfirmation,
    PaymentStatus,
)
from apps.orders import selectors as order_selectors
from common.dates import today_ist
from common.errors import InvalidFields, NotFound
from common.idempotency import idempotent
from common.permissions import HasPermission, StaffReadsOrHasPermission

VIEW, MANAGE = "invoices.view", "invoices.manage"
IDEMPOTENCY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, True)
TAGS = ["billing"]
LINK_RESPONSES = {200: s.DocumentLinkSerializer, 202: s.DocumentLinkSerializer}


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


def _uuid(value: str | None, field: str) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise InvalidFields({field: ["Not a valid id."]}) from exc


def _date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidFields({field: ["Use YYYY-MM-DD."]}) from exc


def _bool(value: str | None) -> bool | None:
    if value in (None, ""):
        return None
    return value.lower() in ("1", "true", "yes")


def _fake(view: Any, model: Any) -> QuerySet[Any] | None:
    return model.objects.unscoped().none() if getattr(view, "swagger_fake_view", False) else None


class Guarded(APIView):
    permission_classes = [HasPermission]


class Newest(CursorPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    ordering = ("-created_at", "-id")


def _invoice(request: Request, invoice_id: UUID) -> Invoice:
    found: Invoice | None = selectors.invoices_for(_user(request)).filter(pk=invoice_id).first()
    if found is None:
        raise NotFound()
    return found


def _note(request: Request, note_id: UUID) -> CreditNote:
    found: CreditNote | None = selectors.credit_notes_for(_user(request)).filter(pk=note_id).first()
    if found is None:
        raise NotFound()
    return found


# --- Invoices ---------------------------------------------------------------------------------


class InvoiceListView(Guarded, generics.ListAPIView[Invoice]):
    required_permission = VIEW
    serializer_class = s.InvoiceRowSerializer
    pagination_class = Newest

    def get_queryset(self) -> QuerySet[Invoice]:
        fake = _fake(self, Invoice)
        if fake is not None:
            return fake
        q = self.request.query_params
        status = q.get("payment_status", "")
        if status and status not in PaymentStatus.values:
            raise InvalidFields({"payment_status": ["Not a valid payment status."]})
        einvoice = q.get("einvoice_status", "")
        if einvoice and einvoice not in EInvoiceStatus.values:
            raise InvalidFields({"einvoice_status": ["Not a valid e-invoice status."]})
        return selectors.invoice_list(
            _user(self.request),
            selectors.InvoiceFilters(
                retailer_id=_uuid(q.get("retailer"), "retailer"),
                payment_status=status,
                overdue=bool(_bool(q.get("overdue"))),
                date_from=_date(q.get("date_from"), "date_from"),
                date_to=_date(q.get("date_to"), "date_to"),
                einvoice_status=einvoice,
                search=q.get("search", ""),
            ),
        )

    @extend_schema(
        operation_id="invoices_list",
        tags=TAGS,
        parameters=[
            OpenApiParameter("retailer", UUID),
            OpenApiParameter("payment_status", str, enum=list(PaymentStatus.values)),
            OpenApiParameter("overdue", bool, description="Only past the due date with a balance"),
            OpenApiParameter("date_from", date),
            OpenApiParameter("date_to", date),
            OpenApiParameter("einvoice_status", str, enum=list(EInvoiceStatus.values)),
            OpenApiParameter("search", str, description="Invoice, order, shop name or code"),
        ],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class InvoiceDetailView(Guarded):
    required_permission = VIEW

    @extend_schema(operation_id="invoices_retrieve", tags=TAGS, responses=s.InvoiceDetailSerializer)
    def get(self, request: Request, invoice_id: UUID) -> Response:
        invoice = selectors.invoice_detail(invoice_id, user=_user(request))
        if invoice is None:
            raise NotFound()
        return Response(s.InvoiceDetailSerializer(invoice).data)


class InvoicePdfView(Guarded):
    required_permission = VIEW

    @extend_schema(
        operation_id="invoices_pdf",
        tags=TAGS,
        parameters=[
            OpenApiParameter(
                "copies",
                bool,
                description="The three labelled copies (original, duplicate, "
                "triplicate) in one PDF, for printing",
            )
        ],
        responses=LINK_RESPONSES,
    )
    def get(self, request: Request, invoice_id: UUID) -> Response:
        invoice = _invoice(request, invoice_id)
        key = (
            invoice.copies_pdf_key if _bool(request.query_params.get("copies")) else invoice.pdf_key
        )
        body, status = documents.link(key, invoice.pdf_status)
        return Response(body, status=status)


class InvoiceRegeneratePdfView(Guarded):
    required_permission = MANAGE

    @extend_schema(
        operation_id="invoices_regenerate_pdf",
        tags=TAGS,
        request=None,
        responses={202: s.DocumentLinkSerializer},
    )
    def post(self, request: Request, invoice_id: UUID) -> Response:
        invoice = _invoice(request, invoice_id)
        with transaction.atomic():
            documents.regenerate("invoice", invoice.pk)
        return Response({"status": "PENDING", "url": None}, status=202)


# --- Credit notes -----------------------------------------------------------------------------


class CreditNoteListCreateView(Guarded, generics.ListAPIView[CreditNote]):
    required_permissions = {"GET": VIEW, "POST": MANAGE}
    serializer_class = s.CreditNoteRowSerializer
    pagination_class = Newest

    def get_queryset(self) -> QuerySet[CreditNote]:
        fake = _fake(self, CreditNote)
        if fake is not None:
            return fake
        q = self.request.query_params
        kind = q.get("kind", "")
        if kind and kind not in CreditNote.Kind.values:
            raise InvalidFields({"kind": ["Not a valid kind."]})
        return selectors.credit_note_list(
            _user(self.request),
            selectors.CreditNoteFilters(
                retailer_id=_uuid(q.get("retailer"), "retailer"),
                invoice_id=_uuid(q.get("invoice"), "invoice"),
                kind=kind,
                automatic=_bool(q.get("automatic")),
                date_from=_date(q.get("date_from"), "date_from"),
                date_to=_date(q.get("date_to"), "date_to"),
                search=q.get("search", ""),
            ),
        )

    @extend_schema(
        operation_id="credit_notes_list",
        tags=TAGS,
        parameters=[
            OpenApiParameter("retailer", UUID),
            OpenApiParameter("invoice", UUID),
            OpenApiParameter("kind", str, enum=list(CreditNote.Kind.values)),
            OpenApiParameter("automatic", bool, description="Issued automatically"),
            OpenApiParameter("date_from", date),
            OpenApiParameter("date_to", date),
            OpenApiParameter("search", str, description="Credit note, invoice or shop name"),
        ],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="credit_notes_create",
        tags=TAGS,
        request=s.CreditNoteCreateSerializer,
        responses={201: s.CreditNoteDetailSerializer},
        parameters=[IDEMPOTENCY],
    )
    @idempotent("billing.credit_notes.create")
    def post(self, request: Request) -> Response:
        data = s.CreditNoteCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        invoice = _invoice(request, v["invoice"])
        if v["kind"] == CreditNote.Kind.RETURN:
            if any("quantity" not in row for row in v["lines"]):
                raise InvalidFields({"lines": ["Enter how many came back on each line."]})
            note = credit_notes.issue_return(
                invoice.pk,
                [
                    ReturnLine(row["invoice_line"], row["quantity"], row["disposition"])
                    for row in v["lines"]
                ],
                reason=v["reason"],
                note=v["note"],
                by=_user(request),
            )
        else:
            if not v["lines"] or any("taxable_value" not in row for row in v["lines"]):
                raise InvalidFields({"lines": ["Enter the taxable value to credit on each line."]})
            amounts: dict[UUID, Decimal] = {}
            for row in v["lines"]:
                if row["invoice_line"] in amounts:
                    raise InvalidFields({"lines": ["Choose each invoice line once."]})
                amounts[row["invoice_line"]] = row["taxable_value"]
            note = credit_notes.issue_price_adjustment(
                invoice.pk, amounts, note=v["note"], by=_user(request)
            )
        detail = selectors.credit_note_detail(note.pk, user=_user(request))
        return Response(s.CreditNoteDetailSerializer(detail).data, status=201)


class CreditNoteDetailView(Guarded):
    required_permission = VIEW

    @extend_schema(
        operation_id="credit_notes_retrieve", tags=TAGS, responses=s.CreditNoteDetailSerializer
    )
    def get(self, request: Request, note_id: UUID) -> Response:
        note = selectors.credit_note_detail(note_id, user=_user(request))
        if note is None:
            raise NotFound()
        return Response(s.CreditNoteDetailSerializer(note).data)


class CreditNotePdfView(Guarded):
    required_permission = VIEW

    @extend_schema(operation_id="credit_notes_pdf", tags=TAGS, responses=LINK_RESPONSES)
    def get(self, request: Request, note_id: UUID) -> Response:
        note = _note(request, note_id)
        body, status = documents.link(note.pdf_key, note.pdf_status)
        return Response(body, status=status)


class CreditNoteRegeneratePdfView(Guarded):
    required_permission = MANAGE

    @extend_schema(
        operation_id="credit_notes_regenerate_pdf",
        tags=TAGS,
        request=None,
        responses={202: s.DocumentLinkSerializer},
    )
    def post(self, request: Request, note_id: UUID) -> Response:
        note = _note(request, note_id)
        with transaction.atomic():
            documents.regenerate("credit_note", note.pk)
        return Response({"status": "PENDING", "url": None}, status=202)


# --- Order Confirmation -----------------------------------------------------------------------


class OrderConfirmationView(Guarded):
    required_permission = "orders.view"

    @extend_schema(
        operation_id="orders_confirmation",
        tags=["orders"],
        responses=LINK_RESPONSES,
        description="Not found when the order has no confirmation (not accepted yet, or the "
        "setting was off when it was placed).",
    )
    def get(self, request: Request, order_id: UUID) -> Response:
        if not order_selectors.orders_for(_user(request)).filter(pk=order_id).exists():
            raise NotFound()
        confirmation = OrderConfirmation.objects.filter(order_id=order_id).first()
        if confirmation is None:
            raise NotFound()
        body, status = documents.link(confirmation.pdf_key, confirmation.pdf_status)
        return Response(body, status=status)


# --- Numbering (ADR-046 item 1) ---------------------------------------------------------------


class DocumentSeriesView(APIView):
    """Invoice, credit note, receipt and refund numbering: any staff member may read; changing
    a prefix needs ``settings.manage`` and applies from the next number (audited)."""

    permission_classes = [StaffReadsOrHasPermission]
    required_permission = "settings.manage"

    @extend_schema(
        operation_id="settings_document_series",
        tags=["settings"],
        responses=s.DocumentSeriesSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        return Response(s.DocumentSeriesSerializer(numbering.overview(today_ist()), many=True).data)

    @extend_schema(
        operation_id="settings_document_series_change",
        tags=["settings"],
        request=s.DocumentSeriesChangeSerializer,
        responses=s.DocumentSeriesSerializer(many=True),
    )
    def patch(self, request: Request) -> Response:
        data = s.DocumentSeriesChangeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            numbering.set_prefix(
                data.validated_data["document_type"],
                data.validated_data["prefix"],
                day=today_ist(),
                by=_user(request),
            )
        return Response(s.DocumentSeriesSerializer(numbering.overview(today_ist()), many=True).data)
