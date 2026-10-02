"""The distributor's orders, shipments and backorders (PLAN §3.8, ADR-044). Thin: permission →
serializer → service/selector. Sales staff limited to their own shops (⚙ orders.sales_visibility)
get "not found" for other shops' orders, as for another tenant's."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.orders import backorders, fulfilment, selectors, transitions
from apps.orders.api import serializers as s
from apps.orders.models import BackorderAllocation, Fulfilment, Order, OrderStatus
from apps.platform.selectors import is_feature_enabled
from common.errors import InvalidFields, NotFound
from common.exceptions import error_body
from common.idempotency import idempotent
from common.permissions import HasPermission

VIEW, MANAGE, FULFIL = "orders.view", "orders.manage", "orders.fulfil"
ALLOCATE, CREDIT = "orders.allocate_backorder", "credit.manage"
IDEMPOTENCY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, True)
TAGS = ["orders"]


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


def _fake(view: Any, model: Any) -> QuerySet[Any] | None:
    return model.objects.unscoped().none() if getattr(view, "swagger_fake_view", False) else None


def _uuid(value: str | None, field: str) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise InvalidFields({field: [_("Not a valid id.")]}) from exc


def _date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidFields({field: [_("Use YYYY-MM-DD.")]}) from exc


class Guarded(APIView):
    permission_classes = [HasPermission]


class Newest(CursorPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    ordering = ("-placed_at", "-id")


class NewestCreated(Newest):
    ordering = ("-created_at", "-id")


def _visible_order(request: Request, order_id: UUID) -> None:
    """404 unless this staff member may see the order (tenant scoping already applies)."""
    if not selectors.orders_for(_user(request)).filter(pk=order_id).exists():
        raise NotFound()


def _detail(request: Request, order_id: UUID, status: int = 200) -> Response:
    order = selectors.order_detail(order_id, user=_user(request))
    if order is None:
        raise NotFound()
    context: dict[str, Any] = {}
    waiting = [line.product_id for line in order.lines.all() if line.qty_backordered > 0]
    if waiting and is_feature_enabled("purchasing"):
        from apps.purchasing.selectors import on_order

        context["on_order"] = on_order(waiting)
    return Response(s.StaffOrderSerializer(order, context=context).data, status=status)


# --- Orders --------------------------------------------------------------------------------------

TAB = OpenApiParameter("tab", str, enum=list(selectors.TABS))
LIST_FILTERS = [
    TAB,
    OpenApiParameter("status", str, enum=list(OrderStatus.values)),
    OpenApiParameter("retailer", UUID),
    OpenApiParameter("salesperson", UUID),
    OpenApiParameter("placed_from", date),
    OpenApiParameter("placed_to", date),
    OpenApiParameter("search", str, description="Order number, shop name or shop code"),
]


class OrderListCreateView(Guarded, generics.ListAPIView[Order]):
    required_permissions = {"GET": VIEW, "POST": "orders.create_on_behalf"}
    serializer_class = s.OrderRowSerializer
    pagination_class = Newest

    def get_queryset(self) -> QuerySet[Order]:
        fake = _fake(self, Order)
        if fake is not None:
            return fake
        q = self.request.query_params
        tab = q.get("tab", "")
        if tab and tab not in selectors.TABS:
            raise InvalidFields(
                {"tab": [_("Use one of: %(tabs)s.") % {"tabs": ", ".join(selectors.TABS)}]}
            )
        status = q.get("status", "")
        if status and status not in OrderStatus.values:
            raise InvalidFields({"status": [_("Not a valid status.")]})
        return selectors.order_list(
            _user(self.request),
            selectors.OrderFilters(
                tab=tab,
                status=status,
                retailer_id=_uuid(q.get("retailer"), "retailer"),
                salesperson_id=_uuid(q.get("salesperson"), "salesperson"),
                placed_from=_date(q.get("placed_from"), "placed_from"),
                placed_to=_date(q.get("placed_to"), "placed_to"),
                search=q.get("search", ""),
            ),
        )

    @extend_schema(operation_id="orders_list", tags=TAGS, parameters=LIST_FILTERS)
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="orders_place_on_behalf",
        tags=TAGS,
        request=s.StaffPlaceOrderSerializer,
        responses={201: s.StaffOrderSerializer},
        parameters=[IDEMPOTENCY],
    )
    @idempotent("orders.place_on_behalf")
    def post(self, request: Request) -> Response:
        from apps.orders.api.staff_cart import place_on_behalf

        data = s.StaffPlaceOrderSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        order = place_on_behalf(request, data.validated_data)
        return _detail(request, order.pk, status=201)


class OrderCountsView(Guarded):
    required_permission = VIEW

    @extend_schema(operation_id="orders_counts", tags=TAGS, responses=s.OrderCountsSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.OrderCountsSerializer(selectors.tab_counts(_user(request))).data)


class OrderDetailView(Guarded):
    required_permission = VIEW

    @extend_schema(operation_id="orders_retrieve", tags=TAGS, responses=s.StaffOrderSerializer)
    def get(self, request: Request, order_id: UUID) -> Response:
        return _detail(request, order_id)


class OrderAcceptView(Guarded):
    required_permission = MANAGE

    @extend_schema(
        operation_id="orders_accept",
        tags=TAGS,
        request=None,
        responses=s.StaffOrderSerializer,
        parameters=[IDEMPOTENCY],
    )
    @idempotent("orders.accept")
    def post(self, request: Request, order_id: UUID) -> Response:
        _visible_order(request, order_id)
        transitions.accept_order(order_id, by=_user(request))
        return _detail(request, order_id)


class OrderRejectView(Guarded):
    required_permission = MANAGE

    @extend_schema(
        operation_id="orders_reject",
        tags=TAGS,
        request=s.RequiredReasonSerializer,
        responses=s.StaffOrderSerializer,
    )
    def post(self, request: Request, order_id: UUID) -> Response:
        data = s.RequiredReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        _visible_order(request, order_id)
        transitions.reject_order(order_id, reason=data.validated_data["reason"], by=_user(request))
        return _detail(request, order_id)


class OrderCancelView(Guarded):
    """Before acceptance the order is cancelled outright; after it, every open shipment and the
    backorder go too (nothing may be dispatched yet)."""

    required_permission = MANAGE

    @extend_schema(
        operation_id="orders_cancel",
        tags=TAGS,
        request=s.RequiredReasonSerializer,
        responses=s.StaffOrderSerializer,
    )
    def post(self, request: Request, order_id: UUID) -> Response:
        data = s.RequiredReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        _visible_order(request, order_id)
        reason, by = data.validated_data["reason"], _user(request)
        status = Order.objects.values_list("status", flat=True).get(pk=order_id)
        if status in (OrderStatus.PLACED, OrderStatus.ON_HOLD):
            transitions.cancel_order(order_id, by=by, reason=reason)
        else:
            fulfilment.cancel_accepted(order_id, reason=reason, by=by)
        return _detail(request, order_id)


class OrderLinesView(Guarded):
    required_permission = MANAGE

    @extend_schema(
        operation_id="orders_modify",
        tags=TAGS,
        request=s.ModifyOrderSerializer,
        responses=s.StaffOrderSerializer,
    )
    def patch(self, request: Request, order_id: UUID) -> Response:
        data = s.ModifyOrderSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        _visible_order(request, order_id)
        transitions.modify_order(
            order_id,
            transitions.Modification(
                quantities={row["line"]: row["quantity"] for row in v["lines"]},
                additions=[(row["product"], row["quantity"]) for row in v["additions"]],
                override_reason=v["override_reason"],
            ),
            by=_user(request),
        )
        return _detail(request, order_id)


class HoldApproveView(Guarded):
    required_permission = CREDIT

    @extend_schema(
        operation_id="orders_hold_approve",
        tags=TAGS,
        request=None,
        responses=s.StaffOrderSerializer,
    )
    def post(self, request: Request, order_id: UUID) -> Response:
        _visible_order(request, order_id)
        transitions.approve_hold(order_id, by=_user(request))
        return _detail(request, order_id)


class HoldRejectView(Guarded):
    required_permission = CREDIT

    @extend_schema(
        operation_id="orders_hold_reject",
        tags=TAGS,
        request=s.RequiredReasonSerializer,
        responses=s.StaffOrderSerializer,
    )
    def post(self, request: Request, order_id: UUID) -> Response:
        data = s.RequiredReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        _visible_order(request, order_id)
        if not Order.objects.filter(pk=order_id, status=OrderStatus.ON_HOLD).exists():
            raise transitions.InvalidTransition(_("This order isn't waiting for credit approval."))
        transitions.reject_order(order_id, reason=data.validated_data["reason"], by=_user(request))
        return _detail(request, order_id)


class CancelBackorderView(Guarded):
    required_permission = MANAGE

    @extend_schema(
        operation_id="order_lines_cancel_backorder",
        tags=TAGS,
        request=None,
        responses=s.StaffOrderSerializer,
    )
    def post(self, request: Request, line_id: UUID) -> Response:
        order_id = (
            selectors.waiting_lines_for(_user(request))
            .filter(pk=line_id)
            .values_list("order_id", flat=True)
            .first()
        )
        if order_id is None:
            raise NotFound()
        backorders.cancel_backorder(line_id, by=_user(request))
        return _detail(request, order_id)


# --- Shipments -----------------------------------------------------------------------------------


class FulfilmentListView(Guarded, generics.ListAPIView[Fulfilment]):
    required_permission = VIEW
    serializer_class = s.FulfilmentRowSerializer
    pagination_class = NewestCreated

    def get_queryset(self) -> QuerySet[Fulfilment]:
        fake = _fake(self, Fulfilment)
        if fake is not None:
            return fake
        status = self.request.query_params.get("status", "")
        if status and status not in Fulfilment.Status.values:
            raise InvalidFields({"status": [_("Not a valid status.")]})
        return selectors.fulfilment_list(_user(self.request), status)

    @extend_schema(
        operation_id="fulfilments_list",
        tags=TAGS,
        parameters=[OpenApiParameter("status", str, enum=list(Fulfilment.Status.values))],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


def _shipment(request: Request, fulfilment_id: UUID) -> Response:
    found = selectors.fulfilment_detail(_user(request), fulfilment_id)
    if found is None:
        raise NotFound()
    return Response(s.FulfilmentDetailSerializer(found).data)


def _visible_shipment(request: Request, fulfilment_id: UUID) -> None:
    if not selectors.fulfilments_for(_user(request)).filter(pk=fulfilment_id).exists():
        raise NotFound()


class FulfilmentDetailView(Guarded):
    required_permission = VIEW

    @extend_schema(
        operation_id="fulfilments_retrieve", tags=TAGS, responses=s.FulfilmentDetailSerializer
    )
    def get(self, request: Request, fulfilment_id: UUID) -> Response:
        return _shipment(request, fulfilment_id)


class PackView(Guarded):
    required_permission = FULFIL

    @extend_schema(
        operation_id="fulfilments_pack",
        tags=TAGS,
        request=s.PackSerializer,
        responses=s.FulfilmentDetailSerializer,
    )
    def post(self, request: Request, fulfilment_id: UUID) -> Response:
        data = s.PackSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        _visible_shipment(request, fulfilment_id)
        packed: dict[UUID, Decimal] = {
            row["line"]: row["quantity"] for row in data.validated_data["lines"]
        }
        fulfilment.pack(fulfilment_id, packed, by=_user(request))
        return _shipment(request, fulfilment_id)


class DispatchView(Guarded):
    required_permission = FULFIL

    @extend_schema(
        operation_id="fulfilments_dispatch",
        tags=TAGS,
        request=s.DispatchSerializer,
        responses=s.FulfilmentDetailSerializer,
    )
    def post(self, request: Request, fulfilment_id: UUID) -> Response:
        data = s.DispatchSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        _visible_shipment(request, fulfilment_id)
        v = data.validated_data
        fulfilment.dispatch(
            fulfilment_id,
            fulfilment.Transport(
                v["vehicle_number"], v["transporter_name"], v["lr_number"], v["distance_km"]
            ),
            by=_user(request),
        )
        return _shipment(request, fulfilment_id)


class DeliverView(Guarded):
    required_permission = FULFIL

    @extend_schema(
        operation_id="fulfilments_deliver",
        tags=TAGS,
        request=s.DeliverSerializer,
        responses=s.FulfilmentDetailSerializer,
    )
    def post(self, request: Request, fulfilment_id: UUID) -> Response:
        data = s.DeliverSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        _visible_shipment(request, fulfilment_id)
        try:
            fulfilment.deliver(
                fulfilment_id,
                by=_user(request),
                code=data.validated_data["code"],
                reason=data.validated_data["reason"],
            )
        except (fulfilment.WrongDeliveryCode, fulfilment.DeliveryCodeLocked) as exc:
            # Answered here, not by the exception handler: that rolls the request's transaction
            # back, and with it the wrong try deliver() counted (five lock the code, ADR-057).
            return Response(
                error_body(exc.code, exc.message, exc.details),
                status=exc.status_code,
                headers=exc.headers,
            )
        return _shipment(request, fulfilment_id)


class CancelShipmentView(Guarded):
    required_permission = MANAGE

    @extend_schema(
        operation_id="fulfilments_cancel",
        tags=TAGS,
        request=s.CancelShipmentSerializer,
        responses=s.FulfilmentDetailSerializer,
    )
    def post(self, request: Request, fulfilment_id: UUID) -> Response:
        data = s.CancelShipmentSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        _visible_shipment(request, fulfilment_id)
        fulfilment.cancel_shipment(
            fulfilment_id,
            to_backorder=data.validated_data["to_backorder"],
            reason=data.validated_data["reason"],
            by=_user(request),
        )
        return _shipment(request, fulfilment_id)


# --- Backorders ----------------------------------------------------------------------------------


class BackorderQueueView(Guarded):
    required_permission = VIEW

    @extend_schema(
        operation_id="backorders_list",
        tags=TAGS,
        parameters=[OpenApiParameter("search", str)],
        responses=s.BackorderGroupSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        groups = selectors.backorder_queue(_user(request), request.query_params.get("search", ""))
        return Response(s.BackorderGroupSerializer(groups, many=True).data)


class BackorderProductView(Guarded):
    required_permission = VIEW

    @extend_schema(
        operation_id="backorders_retrieve",
        tags=TAGS,
        responses=s.WaitingLineSerializer(many=True),
    )
    def get(self, request: Request, product_id: UUID) -> Response:
        lines = selectors.waiting_for_product(_user(request), product_id)[:500]
        return Response(s.WaitingLineSerializer(lines, many=True).data)


class AllocateView(Guarded):
    required_permission = ALLOCATE

    @extend_schema(
        operation_id="backorders_allocate",
        tags=TAGS,
        request=s.AllocateSerializer,
        responses=s.AllocationSerializer(many=True),
        parameters=[IDEMPOTENCY],
    )
    @idempotent("orders.backorders.allocate")
    def post(self, request: Request) -> Response:
        data = s.AllocateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        user = _user(request)
        if v["auto"] == bool(v["allocations"]):
            raise InvalidFields({"allocations": [_("Choose lines, or allocate automatically.")]})
        if v["auto"]:
            made = backorders.run_allocation(
                [v["product"]], trigger=BackorderAllocation.Trigger.MANUAL
            )
        else:
            amounts = {row["order_line"]: row["quantity"] for row in v["allocations"]}
            visible = set(
                selectors.waiting_lines_for(user)
                .filter(pk__in=list(amounts))
                .values_list("pk", flat=True)
            )
            if visible != set(amounts):
                raise NotFound()
            shipments = backorders.allocate_manually(
                v["product"], amounts, by=user, override_reason=v["override_reason"]
            )
            made = list(BackorderAllocation.objects.filter(fulfilment__in=shipments))
        rows = selectors.allocations_for(user).filter(pk__in=[a.pk for a in made])
        return Response(s.AllocationSerializer(rows.order_by("created_at"), many=True).data)


class AllocationListView(Guarded, generics.ListAPIView[BackorderAllocation]):
    required_permission = VIEW
    serializer_class = s.AllocationSerializer
    pagination_class = NewestCreated

    def get_queryset(self) -> QuerySet[BackorderAllocation]:
        fake = _fake(self, BackorderAllocation)
        if fake is not None:
            return fake
        q = self.request.query_params
        status = q.get("status", "")
        if status and status not in BackorderAllocation.Status.values:
            raise InvalidFields({"status": [_("Not a valid status.")]})
        return selectors.allocation_list(
            _user(self.request), status, _uuid(q.get("product"), "product")
        )

    @extend_schema(
        operation_id="backorder_allocations_list",
        tags=TAGS,
        parameters=[
            OpenApiParameter("status", str, enum=list(BackorderAllocation.Status.values)),
            OpenApiParameter("product", UUID),
        ],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


def _visible_allocations(request: Request, ids: list[UUID]) -> None:
    found = selectors.allocations_for(_user(request)).filter(pk__in=ids).count()
    if found != len(set(ids)):
        raise NotFound()


def _allocations(request: Request, ids: list[UUID]) -> Response:
    rows = selectors.allocations_for(_user(request)).filter(pk__in=ids).order_by("created_at")
    return Response(s.AllocationSerializer(rows, many=True).data)


class ConfirmAllocationsView(Guarded):
    required_permission = ALLOCATE

    @extend_schema(
        operation_id="backorder_allocations_confirm",
        tags=TAGS,
        request=s.ConfirmAllocationsSerializer,
        responses=s.AllocationSerializer(many=True),
        parameters=[IDEMPOTENCY],
    )
    @idempotent("orders.backorders.confirm")
    def post(self, request: Request) -> Response:
        data = s.ConfirmAllocationsSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        ids = list(data.validated_data["allocations"])
        _visible_allocations(request, ids)
        backorders.confirm(ids, by=_user(request))
        return _allocations(request, ids)


class RejectAllocationView(Guarded):
    required_permission = ALLOCATE

    @extend_schema(
        operation_id="backorder_allocations_reject",
        tags=TAGS,
        request=None,
        responses=s.AllocationSerializer(many=True),
    )
    def post(self, request: Request, allocation_id: UUID) -> Response:
        _visible_allocations(request, [allocation_id])
        backorders.reject(allocation_id, by=_user(request))
        return _allocations(request, [allocation_id])
