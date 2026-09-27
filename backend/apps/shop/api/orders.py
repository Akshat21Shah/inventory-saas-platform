"""The shop's orders (PLAN §3.9). Placing needs an Idempotency-Key (ADR-005, ADR-044): the app
keeps the same key for a checkout attempt, so a retry after a dropped connection can't create a
second order."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.models import User
from apps.orders import cart as carts
from apps.orders import selectors
from apps.orders.api.serializers import OrderSerializer, PlaceOrderSerializer
from apps.orders.models import Order
from apps.orders.services import Placement, place_order
from apps.shop.api.views import ShopView, _retailer
from common.idempotency import idempotent

IDEMPOTENCY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, True)
PLACE_SCOPE = "shop.orders.place"


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


class ShopOrdersView(ShopView):
    @extend_schema(
        operation_id="shop_orders_place",
        tags=["shop"],
        request=PlaceOrderSerializer,
        responses={201: OrderSerializer},
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
        return Response(OrderSerializer(selectors.order_detail(order.pk)).data, status=201)
