"""The shop's cart (PLAN §3.9): every response is the whole cart, priced by the server."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.models import User
from apps.orders import cart as carts
from apps.orders.api.quote_serializers import DeliveryAddressSerializer, QuoteSerializer
from apps.pricing.api.serializers import qty
from apps.retailers.models import RetailerAddress
from apps.shop.api.views import ShopView, _retailer
from common.errors import InvalidFields

ADDRESS = OpenApiParameter("address", UUID, description="A saved address (default: shipping)")


class QuantitySerializer(serializers.Serializer[Any]):
    quantity = qty(min_value=0)


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


def _address(request: Request) -> UUID | None:
    raw = request.query_params.get("address")
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError as exc:
        raise InvalidFields({"address": ["Not a valid address."]}) from exc


def cart_response(request: Request) -> Response:
    cart = carts.cart_for(_retailer(request), _user(request))
    return Response(QuoteSerializer(carts.quote(cart, address_id=_address(request))).data)


class ShopCartView(ShopView):
    @extend_schema(
        operation_id="shop_cart_retrieve",
        tags=["shop"],
        parameters=[ADDRESS],
        responses=QuoteSerializer,
    )
    def get(self, request: Request) -> Response:
        return cart_response(request)

    @extend_schema(operation_id="shop_cart_clear", tags=["shop"], responses=QuoteSerializer)
    def delete(self, request: Request) -> Response:
        carts.clear(carts.cart_for(_retailer(request), _user(request)))
        return cart_response(request)


class ShopCartLineView(ShopView):
    @extend_schema(
        operation_id="shop_cart_line_set",
        tags=["shop"],
        request=QuantitySerializer,
        responses=QuoteSerializer,
        parameters=[ADDRESS],
    )
    def put(self, request: Request, product_id: UUID) -> Response:
        data = QuantitySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        cart = carts.cart_for(_retailer(request), _user(request))
        carts.set_quantity(cart, product_id, data.validated_data["quantity"])
        return cart_response(request)

    @extend_schema(
        operation_id="shop_cart_line_remove",
        tags=["shop"],
        responses=QuoteSerializer,
        parameters=[ADDRESS],
    )
    def delete(self, request: Request, product_id: UUID) -> Response:
        cart = carts.cart_for(_retailer(request), _user(request))
        carts.set_quantity(cart, product_id, Decimal("0"))
        return cart_response(request)


class ShopCartReduceView(ShopView):
    @extend_schema(
        operation_id="shop_cart_reduce_to_available",
        tags=["shop"],
        request=None,
        responses=QuoteSerializer,
        parameters=[ADDRESS],
    )
    def post(self, request: Request) -> Response:
        carts.reduce_to_available(carts.cart_for(_retailer(request), _user(request)))
        return cart_response(request)


class ShopAddressesView(ShopView):
    @extend_schema(
        operation_id="shop_addresses_list",
        tags=["shop"],
        responses=DeliveryAddressSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        rows = (
            RetailerAddress.objects.filter(retailer=_retailer(request))
            .select_related("state")
            .order_by("-is_default", "-kind", "label")
        )
        return Response(DeliveryAddressSerializer(rows, many=True).data)
