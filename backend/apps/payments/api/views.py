"""Offline payments, salesman collections, handover and reallocation (PLAN §3.10, ADR-046).
Thin: permission → serializer → service/selector. Recording and collecting need an
Idempotency-Key; sales staff limited to their own shops see only those shops' payments."""

from datetime import date
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
from apps.billing import documents
from apps.billing.api.serializers import DocumentLinkSerializer
from apps.ledger.models import Allocation
from apps.ledger.selectors import used_for_rows
from apps.payments import selectors, services
from apps.payments.api import serializers as s
from apps.payments.models import Payment, Refund
from apps.payments.services import DueAmount, PaymentInput
from apps.retailers.selectors import retailer_for
from common.errors import InvalidFields, NotFound
from common.idempotency import idempotent
from common.permissions import HasPermission

VIEW, RECORD, REVERSE = "payments.view", "payments.record", "payments.reverse"
IDEMPOTENCY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, True)
TAGS = ["payments"]


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


class Guarded(APIView):
    permission_classes = [HasPermission]


class Newest(CursorPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    ordering = ("-created_at", "-id")


def _payment(request: Request, payment_id: UUID) -> Payment:
    found: Payment | None = selectors.payments_for(_user(request)).filter(pk=payment_id).first()
    if found is None:
        raise NotFound()
    return found


def _detail(request: Request, payment_id: UUID, status: int = 200) -> Response:
    payment = selectors.payment_detail(payment_id, user=_user(request))
    if payment is None:
        raise NotFound()
    return Response(s.PaymentDetailSerializer(payment).data, status=status)


def _dues(rows: list[dict[str, Any]]) -> tuple[DueAmount, ...]:
    return tuple(DueAmount(r["target_type"], r["target_id"], r["amount"]) for r in rows)


def _input(v: dict[str, Any], retailer_id: UUID) -> PaymentInput:
    return PaymentInput(
        retailer_id=retailer_id,
        amount=v["amount"],
        mode=v["mode"],
        payment_date=v["payment_date"],
        reference_no=v["reference_no"],
        cheque_number=v["cheque_number"],
        cheque_date=v["cheque_date"],
        bank_name=v["bank_name"],
        notes=v["notes"],
        pay_first=_dues(v.get("pay_first", [])),
    )


def _visible_shop(request: Request, retailer_id: UUID) -> UUID:
    shop = retailer_for(_user(request), retailer_id)
    if shop is None:
        raise NotFound()
    return shop.pk


class PaymentListCreateView(Guarded, generics.ListAPIView[Payment]):
    required_permissions = {"GET": VIEW, "POST": RECORD}
    serializer_class = s.PaymentRowSerializer
    pagination_class = Newest

    def get_queryset(self) -> QuerySet[Payment]:
        if getattr(self, "swagger_fake_view", False):
            return Payment.objects.unscoped().none()
        q = self.request.query_params
        for field, allowed in (
            ("mode", Payment.Mode.values),
            ("status", Payment.Status.values),
            ("handover_status", Payment.Handover.values),
        ):
            if q.get(field) and q[field] not in allowed:
                raise InvalidFields({field: ["Not a valid value."]})
        return selectors.payment_list(
            _user(self.request),
            selectors.PaymentFilters(
                retailer_id=_uuid(q.get("retailer"), "retailer"),
                mode=q.get("mode", ""),
                status=q.get("status", ""),
                handover_status=q.get("handover_status", ""),
                collected_by=_uuid(q.get("collected_by"), "collected_by"),
                date_from=_date(q.get("date_from"), "date_from"),
                date_to=_date(q.get("date_to"), "date_to"),
                search=q.get("search", ""),
            ),
        )

    @extend_schema(
        operation_id="payments_list",
        tags=TAGS,
        parameters=[
            OpenApiParameter("retailer", UUID),
            OpenApiParameter("mode", str, enum=list(Payment.Mode.values)),
            OpenApiParameter("status", str, enum=list(Payment.Status.values)),
            OpenApiParameter("handover_status", str, enum=list(Payment.Handover.values)),
            OpenApiParameter("collected_by", UUID),
            OpenApiParameter("date_from", date),
            OpenApiParameter("date_to", date),
            OpenApiParameter("search", str, description="Receipt, shop, reference or cheque"),
        ],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="payments_record",
        tags=TAGS,
        request=s.RecordPaymentSerializer,
        responses={201: s.PaymentDetailSerializer},
        parameters=[IDEMPOTENCY],
    )
    @idempotent("payments.record")
    def post(self, request: Request) -> Response:
        data = s.RecordPaymentSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        shop = _visible_shop(request, v["retailer"])
        payment = services.record_payment(_input(v, shop), by=_user(request))
        return _detail(request, payment.pk, status=201)


class CollectView(Guarded):
    required_permission = "payments.collect"

    @extend_schema(
        operation_id="payments_collect",
        tags=TAGS,
        request=s.CollectSerializer,
        responses={201: s.PaymentDetailSerializer},
        parameters=[IDEMPOTENCY],
        description="A salesman's collection from one of their shops. It is credited to the shop "
        'at once and stays "With salesman" until someone who records payments confirms it was '
        "handed over.",
    )
    @idempotent("payments.collect")
    def post(self, request: Request) -> Response:
        data = s.CollectSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        payment = services.collect_payment(_input(v, v["retailer"]), by=_user(request))
        found = selectors.payment_detail(payment.pk, retailer_id=payment.retailer_id)
        return Response(s.PaymentDetailSerializer(found).data, status=201)


class PaymentDetailView(Guarded):
    required_permission = VIEW

    @extend_schema(operation_id="payments_retrieve", tags=TAGS, responses=s.PaymentDetailSerializer)
    def get(self, request: Request, payment_id: UUID) -> Response:
        return _detail(request, payment_id)


class AllocateView(Guarded):
    required_permission = RECORD

    @extend_schema(
        operation_id="payments_allocate",
        tags=TAGS,
        request=s.PaymentAllocateSerializer,
        responses=s.PaymentDetailSerializer,
    )
    def post(self, request: Request, payment_id: UUID) -> Response:
        data = s.PaymentAllocateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        payment = _payment(request, payment_id)
        services.allocate(
            payment.retailer_id,
            source_type="PAYMENT",
            source_id=payment.pk,
            to=list(_dues(data.validated_data["to"])),
            by=_user(request),
            reason=data.validated_data["reason"],
        )
        return _detail(request, payment.pk)


class ClearView(Guarded):
    required_permission = RECORD

    @extend_schema(
        operation_id="payments_clear",
        tags=TAGS,
        request=s.ClearSerializer,
        responses=s.PaymentDetailSerializer,
    )
    def post(self, request: Request, payment_id: UUID) -> Response:
        data = s.ClearSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        payment = _payment(request, payment_id)
        services.clear_cheque(payment.pk, on=data.validated_data["on"], by=_user(request))
        return _detail(request, payment.pk)


class BounceView(Guarded):
    required_permission = REVERSE

    @extend_schema(
        operation_id="payments_bounce",
        tags=TAGS,
        request=s.PaymentReasonSerializer,
        responses=s.PaymentDetailSerializer,
    )
    def post(self, request: Request, payment_id: UUID) -> Response:
        data = s.PaymentReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        payment = _payment(request, payment_id)
        services.bounce_cheque(payment.pk, reason=data.validated_data["reason"], by=_user(request))
        return _detail(request, payment.pk)


class ReverseView(Guarded):
    required_permission = REVERSE

    @extend_schema(
        operation_id="payments_reverse",
        tags=TAGS,
        request=s.PaymentReasonSerializer,
        responses=s.PaymentDetailSerializer,
    )
    def post(self, request: Request, payment_id: UUID) -> Response:
        data = s.PaymentReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        payment = _payment(request, payment_id)
        services.reverse_payment(
            payment.pk, reason=data.validated_data["reason"], by=_user(request)
        )
        return _detail(request, payment.pk)


class ReceiptView(Guarded):
    required_permission = VIEW

    @extend_schema(
        operation_id="payments_receipt",
        tags=TAGS,
        responses={200: DocumentLinkSerializer, 202: DocumentLinkSerializer},
    )
    def get(self, request: Request, payment_id: UUID) -> Response:
        payment = _payment(request, payment_id)
        body, status = documents.link(payment.receipt_pdf_key, payment.receipt_pdf_status)
        return Response(body, status=status)


class HandoverView(Guarded):
    required_permission = RECORD

    @extend_schema(
        operation_id="payments_handover",
        tags=TAGS,
        request=s.HandoverSerializer,
        responses=s.HandoverResultSerializer,
    )
    def post(self, request: Request) -> Response:
        data = s.HandoverSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        ids = data.validated_data["payments"]
        visible = set(
            selectors.payments_for(_user(request)).filter(pk__in=ids).values_list("pk", flat=True)
        )
        if visible != set(ids):
            raise NotFound()
        payments = services.hand_over(list(ids), by=_user(request))
        return Response(s.HandoverResultSerializer({"payments": payments}).data)


class PendingHandoverView(Guarded):
    required_permission = RECORD

    @extend_schema(
        operation_id="reports_collections_pending_handover",
        tags=TAGS,
        responses=s.PendingHandoverSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        return Response(
            s.PendingHandoverSerializer(selectors.collections_pending_handover(), many=True).data
        )


class AllocationReverseView(Guarded):
    required_permission = RECORD

    @extend_schema(
        operation_id="payment_allocations_reverse",
        tags=TAGS,
        request=s.ReallocateSerializer,
        responses=s.ReallocationResultSerializer,
        description="Undo an allocation (automatic or by hand) and optionally match the money to "
        "other dues in the same step. Audited.",
    )
    def post(self, request: Request, allocation_id: UUID) -> Response:
        data = s.ReallocateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        retailer_id = (
            Allocation.objects.filter(pk=allocation_id)
            .values_list("retailer_id", flat=True)
            .first()
        )
        if retailer_id is None or retailer_for(_user(request), retailer_id) is None:
            raise NotFound()
        undo, made = services.reallocate(
            allocation_id,
            to=list(_dues(data.validated_data["to"])),
            reason=data.validated_data["reason"],
            by=_user(request),
        )
        rows = used_for_rows([undo, *made])
        return Response(
            s.ReallocationResultSerializer({"reversal": rows[0], "reallocated": rows[1:]}).data
        )


class ReceiptRegenerateView(Guarded):
    required_permission = RECORD

    @extend_schema(
        operation_id="payments_regenerate_receipt",
        tags=TAGS,
        request=None,
        responses={202: DocumentLinkSerializer},
    )
    def post(self, request: Request, payment_id: UUID) -> Response:
        payment = _payment(request, payment_id)
        with transaction.atomic():
            documents.regenerate("receipt", payment.pk)
        return Response({"status": "PENDING", "url": None}, status=202)


# --- Refunds (ADR-047) ------------------------------------------------------------------------


def _refund(request: Request, refund_id: UUID) -> Refund:
    found: Refund | None = selectors.refunds_for(_user(request)).filter(pk=refund_id).first()
    if found is None:
        raise NotFound()
    return found


class RefundListCreateView(Guarded, generics.ListAPIView[Refund]):
    required_permissions = {"GET": VIEW, "POST": RECORD}
    serializer_class = s.RefundSerializer
    pagination_class = Newest

    def get_queryset(self) -> QuerySet[Refund]:
        if getattr(self, "swagger_fake_view", False):
            return Refund.objects.unscoped().none()
        qs = selectors.refunds_for(_user(self.request))
        retailer = _uuid(self.request.query_params.get("retailer"), "retailer")
        return qs.filter(retailer_id=retailer) if retailer else qs

    @extend_schema(
        operation_id="refunds_list", tags=TAGS, parameters=[OpenApiParameter("retailer", UUID)]
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="refunds_record",
        tags=TAGS,
        request=s.RefundCreateSerializer,
        responses={201: s.RefundDetailSerializer},
        parameters=[IDEMPOTENCY],
        description="Pay a shop back from its credit balance (never more than it has).",
    )
    @idempotent("payments.refunds.record")
    def post(self, request: Request) -> Response:
        data = s.RefundCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        shop = _visible_shop(request, v["retailer"])
        refund = services.record_refund(
            services.RefundInput(
                retailer_id=shop,
                amount=v["amount"],
                mode=v["mode"],
                refund_date=v["refund_date"],
                reference_no=v["reference_no"],
                notes=v["notes"],
            ),
            by=_user(request),
        )
        detail = selectors.refund_detail(refund.pk, user=_user(request))
        return Response(s.RefundDetailSerializer(detail).data, status=201)


class RefundDetailView(Guarded):
    required_permission = VIEW

    @extend_schema(operation_id="refunds_retrieve", tags=TAGS, responses=s.RefundDetailSerializer)
    def get(self, request: Request, refund_id: UUID) -> Response:
        refund = selectors.refund_detail(refund_id, user=_user(request))
        if refund is None:
            raise NotFound()
        return Response(s.RefundDetailSerializer(refund).data)


class RefundVoucherView(Guarded):
    required_permission = VIEW

    @extend_schema(
        operation_id="refunds_voucher",
        tags=TAGS,
        responses={200: DocumentLinkSerializer, 202: DocumentLinkSerializer},
    )
    def get(self, request: Request, refund_id: UUID) -> Response:
        refund = _refund(request, refund_id)
        body, status = documents.link(refund.voucher_pdf_key, refund.voucher_pdf_status)
        return Response(body, status=status)


class RefundRegenerateVoucherView(Guarded):
    required_permission = RECORD

    @extend_schema(
        operation_id="refunds_regenerate_voucher",
        tags=TAGS,
        request=None,
        responses={202: DocumentLinkSerializer},
    )
    def post(self, request: Request, refund_id: UUID) -> Response:
        refund = _refund(request, refund_id)
        with transaction.atomic():
            documents.regenerate("refund", refund.pk)
        return Response({"status": "PENDING", "url": None}, status=202)


class RefundReverseView(Guarded):
    """A refund entered in error: the shop's credit is restored (``payments.record``)."""

    required_permission = RECORD

    @extend_schema(
        operation_id="refunds_reverse",
        tags=TAGS,
        request=s.PaymentReasonSerializer,
        responses=s.RefundDetailSerializer,
    )
    def post(self, request: Request, refund_id: UUID) -> Response:
        data = s.PaymentReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        refund = _refund(request, refund_id)
        services.reverse_refund(refund.pk, reason=data.validated_data["reason"], by=_user(request))
        detail = selectors.refund_detail(refund.pk, user=_user(request))
        return Response(s.RefundDetailSerializer(detail).data)
