"""The shop's bills, statement and payments (PLAN §3.9). Everything is the shop's own: another
shop's documents are "not found"."""

from typing import Any
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response

from apps.billing import documents
from apps.billing import selectors as billing
from apps.billing.api.serializers import (
    DocumentLinkSerializer,
    InvoiceDetailSerializer,
    InvoiceRowSerializer,
)
from apps.billing.models import CreditNote, Invoice, OrderConfirmation
from apps.ledger import selectors as ledger
from apps.ledger.api.serializers import BucketsSerializer, PositionSerializer, StatementSerializer
from apps.ledger.api.views import statement_for
from apps.orders import credit
from apps.payments import selectors as payments
from apps.payments.api.serializers import PaymentDetailSerializer, PaymentRowSerializer
from apps.payments.models import Payment
from apps.pricing.api.serializers import money
from apps.shop.api.views import ShopView, _retailer
from common.dates import today_ist
from common.errors import InvalidFields, NotFound

TAGS = ["shop"]
LINK = {200: DocumentLinkSerializer, 202: DocumentLinkSerializer}
STATES = ("unpaid", "paid", "overdue")


class Newest(CursorPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50
    ordering = ("-created_at", "-id")


class ShopInvoicesView(ShopView):
    pagination_class = Newest

    @extend_schema(
        operation_id="shop_invoices_list",
        tags=TAGS,
        parameters=[
            OpenApiParameter("state", str, enum=list(STATES)),
            OpenApiParameter("cursor", str),
            OpenApiParameter("page_size", int),
        ],
        responses=InvoiceRowSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        state = request.query_params.get("state", "")
        if state and state not in STATES:
            raise InvalidFields({"state": ["Use unpaid, paid or overdue."]})
        qs = Invoice.objects.filter(retailer=_retailer(request)).select_related("retailer", "order")
        if state == "paid":
            qs = qs.filter(balance_due=0)
        elif state == "unpaid":
            qs = qs.filter(balance_due__gt=0)
        elif state == "overdue":
            qs = qs.filter(balance_due__gt=0, due_date__lt=today_ist())
        paginator = Newest()
        page = paginator.paginate_queryset(qs, request, view=self) or []
        return paginator.get_paginated_response(InvoiceRowSerializer(page, many=True).data)


class ShopInvoiceDetailView(ShopView):
    @extend_schema(
        operation_id="shop_invoices_retrieve", tags=TAGS, responses=InvoiceDetailSerializer
    )
    def get(self, request: Request, invoice_id: UUID) -> Response:
        invoice = billing.invoice_detail(invoice_id, retailer_id=_retailer(request).pk)
        if invoice is None:
            raise NotFound()
        return Response(InvoiceDetailSerializer(invoice).data)


class ShopInvoicePdfView(ShopView):
    @extend_schema(operation_id="shop_invoices_pdf", tags=TAGS, responses=LINK)
    def get(self, request: Request, invoice_id: UUID) -> Response:
        invoice = Invoice.objects.filter(pk=invoice_id, retailer=_retailer(request)).first()
        if invoice is None:
            raise NotFound()
        body, status = documents.link(invoice.pdf_key, invoice.pdf_status)  # the original only
        return Response(body, status=status)


class ShopCreditNotePdfView(ShopView):
    @extend_schema(operation_id="shop_credit_notes_pdf", tags=TAGS, responses=LINK)
    def get(self, request: Request, note_id: UUID) -> Response:
        note = CreditNote.objects.filter(pk=note_id, retailer=_retailer(request)).first()
        if note is None:
            raise NotFound()
        body, status = documents.link(note.pdf_key, note.pdf_status)
        return Response(body, status=status)


class ShopLedgerView(ShopView):
    @extend_schema(
        operation_id="shop_ledger",
        tags=TAGS,
        parameters=[OpenApiParameter("date_from", str), OpenApiParameter("date_to", str)],
        responses=StatementSerializer,
    )
    def get(self, request: Request) -> Response:
        return Response(StatementSerializer(statement_for(_retailer(request), request)).data)


class ShopAccountSerializer(serializers.Serializer[Any]):
    position = PositionSerializer()
    credit_limit = money(allow_null=True)
    available_credit = money(allow_null=True, help_text="Null without a limit.")
    ageing_basis = serializers.ChoiceField(choices=["INVOICE_DATE", "DUE_DATE"])
    ageing = BucketsSerializer()
    overdue_bills = serializers.IntegerField()
    orders_blocked_for_overdue = serializers.BooleanField(
        help_text="New orders wait for approval or are refused until overdue bills are paid."
    )


class ShopAccountView(ShopView):
    @extend_schema(operation_id="shop_account", tags=TAGS, responses=ShopAccountSerializer)
    def get(self, request: Request) -> Response:
        shop = _retailer(request)
        basis, rows = ledger.ageing([shop.pk])
        buckets = rows[0].buckets if rows else dict.fromkeys(ledger.BUCKETS, ledger.ZERO)
        status = credit.check(shop, credit.ZERO, breach_action="BLOCK")
        body = {
            "position": ledger.outstanding(shop.pk),
            "credit_limit": status.limit,
            "available_credit": status.available,
            "ageing_basis": basis,
            "ageing": buckets,
            "overdue_bills": Invoice.objects.filter(
                retailer=shop, balance_due__gt=0, due_date__lt=today_ist()
            ).count(),
            "orders_blocked_for_overdue": status.reason == credit.BreachReason.OVERDUE,
        }
        return Response(ShopAccountSerializer(body).data)


class ShopPaymentsView(ShopView):
    pagination_class = Newest

    @extend_schema(
        operation_id="shop_payments_list",
        tags=TAGS,
        parameters=[OpenApiParameter("cursor", str), OpenApiParameter("page_size", int)],
        responses=PaymentRowSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        qs = Payment.objects.filter(retailer=_retailer(request)).select_related(
            "retailer", "collected_by"
        )
        paginator = Newest()
        page = paginator.paginate_queryset(qs, request, view=self) or []
        return paginator.get_paginated_response(PaymentRowSerializer(page, many=True).data)


class ShopPaymentDetailView(ShopView):
    @extend_schema(
        operation_id="shop_payments_retrieve", tags=TAGS, responses=PaymentDetailSerializer
    )
    def get(self, request: Request, payment_id: UUID) -> Response:
        payment = payments.payment_detail(payment_id, retailer_id=_retailer(request).pk)
        if payment is None:
            raise NotFound()
        return Response(PaymentDetailSerializer(payment).data)


class ShopReceiptView(ShopView):
    @extend_schema(operation_id="shop_payments_receipt", tags=TAGS, responses=LINK)
    def get(self, request: Request, payment_id: UUID) -> Response:
        payment = Payment.objects.filter(pk=payment_id, retailer=_retailer(request)).first()
        if payment is None:
            raise NotFound()
        body, status = documents.link(payment.receipt_pdf_key, payment.receipt_pdf_status)
        return Response(body, status=status)


class ShopOrderConfirmationView(ShopView):
    @extend_schema(operation_id="shop_orders_confirmation", tags=TAGS, responses=LINK)
    def get(self, request: Request, order_id: UUID) -> Response:
        confirmation = OrderConfirmation.objects.filter(
            order_id=order_id, order__retailer=_retailer(request)
        ).first()
        if confirmation is None:
            raise NotFound()
        body, status = documents.link(confirmation.pdf_key, confirmation.pdf_status)
        return Response(body, status=status)
