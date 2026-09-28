"""The shop's orders (PLAN §3.9, ADR-044). Placing needs an Idempotency-Key (ADR-005): the app
keeps the same key for a checkout attempt, so a retry after a dropped connection can't create a
second order; when it can't tell whether an attempt got through, it asks ``checkout-attempts``
before retrying."""

from typing import Any
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.orders import backorders, credit, selectors, transitions
from apps.orders import cart as carts
from apps.orders.api.serializers import PlaceOrderSerializer
from apps.orders.models import Order
from apps.orders.services import Placement, place_order
from apps.shop import selectors as shop_selectors
from apps.shop.api import serializers as s
from apps.shop.api.views import ShopView, _context, _retailer
from common.errors import InvalidFields, NotFound
from common.idempotency import _KEY_RE, idempotent
from common.models import IdempotencyRecord

IDEMPOTENCY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, True)
PLACE_SCOPE = "shop.orders.place"
TAGS = ["shop"]


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


def _order(request: Request, order_id: UUID, status: int = 200) -> Response:
    found = selectors.shop_order(_retailer(request).pk, order_id)
    if found is None:
        raise NotFound()
    return Response(s.ShopOrderSerializer(found).data, status=status)


class Newest(CursorPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50
    ordering = ("-placed_at", "-id")


class ShopOrdersView(ShopView):
    pagination_class = Newest  # documents the list as a cursor page

    @extend_schema(
        operation_id="shop_orders_list",
        tags=TAGS,
        parameters=[
            OpenApiParameter("state", str, enum=list(selectors.SHOP_STATES)),
            OpenApiParameter("cursor", str),
            OpenApiParameter("page_size", int),
        ],
        responses=s.ShopOrderRowSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        state = request.query_params.get("state", "")
        if state and state not in selectors.SHOP_STATES:
            raise InvalidFields({"state": ["Use open or closed."]})
        paginator = Newest()
        qs = selectors.shop_orders(_retailer(request).pk, state)
        page = paginator.paginate_queryset(qs, request, view=self) or []
        return paginator.get_paginated_response(s.ShopOrderRowSerializer(page, many=True).data)

    @extend_schema(
        operation_id="shop_orders_place",
        tags=TAGS,
        request=PlaceOrderSerializer,
        responses={201: s.ShopOrderSerializer},
        parameters=[IDEMPOTENCY],
    )
    @idempotent(PLACE_SCOPE)
    def post(self, request: Request) -> Response:
        data = PlaceOrderSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        retailer = _retailer(request)
        cart = carts.cart_for(retailer, _user(request))
        order = place_order(
            Placement(
                retailer=retailer,
                placed_by=_user(request),
                via=Order.PlacedVia.RETAILER_APP,
                items=carts.items(cart),
                expected_total=data.validated_data["expected_total"],
                address_id=data.validated_data["address"],
                note=data.validated_data["note"],
                cart=cart,
            )
        )
        return _order(request, order.pk, status=201)


class ShopOrderDetailView(ShopView):
    @extend_schema(operation_id="shop_order", tags=TAGS, responses=s.ShopOrderSerializer)
    def get(self, request: Request, order_id: UUID) -> Response:
        return _order(request, order_id)


class ShopOrderCancelView(ShopView):
    @extend_schema(
        operation_id="shop_order_cancel",
        tags=TAGS,
        request=s.CancelOrderSerializer,
        responses=s.ShopOrderSerializer,
    )
    def post(self, request: Request, order_id: UUID) -> Response:
        data = s.CancelOrderSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        retailer = _retailer(request)
        transitions.cancel_order(
            order_id,
            by=_user(request),
            reason=data.validated_data["reason"],
            retailer_id=retailer.pk,
        )
        return _order(request, order_id)


class ShopOrderRepeatView(ShopView):
    @extend_schema(
        operation_id="shop_order_repeat",
        tags=TAGS,
        request=None,
        responses=s.RepeatResultSerializer,
    )
    def post(self, request: Request, order_id: UUID) -> Response:
        retailer = _retailer(request)
        order = selectors.shop_order(retailer.pk, order_id)
        if order is None:
            raise NotFound()
        cart = carts.cart_for(retailer, _user(request))
        skipped = carts.add_quantities(cart, selectors.repeat_quantities(order))
        names = dict(Product.objects.filter(pk__in=skipped).values_list("pk", "name"))
        return Response(
            s.RepeatResultSerializer(
                {
                    "cart": carts.quote(cart),
                    "skipped": [{"product_id": pid, "name": names.get(pid, "")} for pid in skipped],
                }
            ).data
        )


class ShopCancelBackorderView(ShopView):
    @extend_schema(
        operation_id="shop_order_line_cancel_backorder",
        tags=TAGS,
        request=None,
        responses=s.ShopOrderSerializer,
    )
    def post(self, request: Request, line_id: UUID) -> Response:
        retailer = _retailer(request)
        line = backorders.cancel_backorder(line_id, by=_user(request), retailer_id=retailer.pk)
        return _order(request, line.order_id)


class ShopCancelRepricedView(ShopView):
    @extend_schema(
        operation_id="shop_fulfilment_line_cancel_repriced",
        tags=TAGS,
        request=None,
        responses=s.ShopOrderSerializer,
    )
    def post(self, request: Request, line_id: UUID) -> Response:
        retailer = _retailer(request)
        fl = backorders.cancel_repriced(line_id, by=_user(request), retailer_id=retailer.pk)
        order_id = Order.objects.filter(fulfilments__lines=fl).values_list("pk", flat=True).get()
        return _order(request, order_id)


class ShopCheckoutAttemptView(ShopView):
    """Did the checkout attempt with this Idempotency-Key place an order? Only this user's own
    attempts; an attempt still running shows as not found, and retrying with the same key then
    waits for it and returns its result."""

    @extend_schema(
        operation_id="shop_checkout_attempt",
        tags=TAGS,
        responses=s.CheckoutAttemptSerializer,
    )
    def get(self, request: Request, key: str) -> Response:
        if not _KEY_RE.match(key):
            raise InvalidFields({"key": ["Not a valid checkout key."]})
        retailer = _retailer(request)
        record = IdempotencyRecord.objects.filter(
            user=_user(request), scope=PLACE_SCOPE, key=key, response_status=201
        ).first()
        body: dict[str, Any] = {"status": "not_found", "order": None, "number": None}
        if record is not None and isinstance(record.response_body, dict):
            found = (
                Order.objects.filter(pk=record.response_body.get("id"), retailer=retailer)
                .values_list("pk", "number")
                .first()
            )
            if found is not None:
                body = {"status": "placed", "order": found[0], "number": found[1]}
        return Response(s.CheckoutAttemptSerializer(body).data)


class ShopHomeView(ShopView):
    @extend_schema(operation_id="shop_home", tags=TAGS, responses=s.ShopHomeSerializer)
    def get(self, request: Request) -> Response:
        retailer = _retailer(request)
        recent = list(selectors.shop_orders(retailer.pk).order_by("-placed_at", "-id")[:5])
        last = selectors.last_order(retailer.pk)
        last_order = None
        if last is not None:
            items = shop_selectors.repeat_items(retailer, selectors.repeat_quantities(last))
            last_order = {
                "id": last.pk,
                "number": last.number,
                "placed_at": last.placed_at,
                "items": items,
            }
        status = credit.check(retailer, credit.ZERO, breach_action="BLOCK")
        body = {
            "recent_orders": recent,
            "last_order": last_order,
            "open_orders": selectors.shop_orders(retailer.pk, "open").count(),
            "waiting_items": selectors.waiting_items(retailer.pk),
            "credit": {"limit": status.limit, "available": status.available},
        }
        return Response(s.ShopHomeSerializer(body, context=_context(retailer)).data)
