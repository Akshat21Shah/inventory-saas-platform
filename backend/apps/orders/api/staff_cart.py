"""Staff ordering on a shop's behalf (PLAN B7, ADR-044): a separate cart per (shop, staff member),
priced for the shop, placed with ``placed_via=STAFF`` and "Placed by Priya (Sales)". Needs
``orders.create_on_behalf`` and ⚙ orders.staff_can_place_on_behalf; sales staff limited to their
own shops can order only for those."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.orders import cart as carts
from apps.orders.api.quote_serializers import QuantitySerializer, QuoteSerializer
from apps.orders.models import Order
from apps.orders.services import Placement, place_order
from apps.platform.selectors import get_setting
from apps.retailers.models import Retailer
from apps.retailers.selectors import retailers_for
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields, NotFound
from common.permissions import HasPermission
from common.tenancy import require_tenant_id

ON_BEHALF = "orders.create_on_behalf"
ADDRESS = OpenApiParameter("address", UUID, description="A saved address (default: shipping)")
TAGS = ["orders"]


class OnBehalfDisabled(DomainError):
    status_code = 403
    code = ErrorCode.PERMISSION_DENIED
    default_message = "Ordering for shops is switched off in your settings."


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


def shop_for(request: Request, retailer_id: UUID) -> Retailer:
    """The shop a staff member may order for (404 for shops they can't see)."""
    if not get_setting("orders.staff_can_place_on_behalf", require_tenant_id()):
        raise OnBehalfDisabled()
    retailer: Retailer | None = retailers_for(_user(request)).filter(pk=retailer_id).first()
    if retailer is None:
        raise NotFound()
    return retailer


def _address(request: Request) -> UUID | None:
    raw = request.query_params.get("address")
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError as exc:
        raise InvalidFields({"address": ["Not a valid address."]}) from exc


def _cart_response(request: Request, retailer: Retailer) -> Response:
    cart = carts.cart_for(retailer, _user(request))
    return Response(QuoteSerializer(carts.quote(cart, address_id=_address(request))).data)


def place_on_behalf(request: Request, data: dict[str, Any]) -> Order:
    retailer = shop_for(request, data["retailer"])
    cart = carts.cart_for(retailer, _user(request))
    return place_order(
        Placement(
            retailer=retailer,
            placed_by=_user(request),
            via=Order.PlacedVia.STAFF,
            items=carts.items(cart),
            expected_total=data["expected_total"],
            address_id=data["address"],
            note=data["note"],
            cart=cart,
        )
    )


class Guarded(APIView):
    permission_classes = [HasPermission]
    required_permission = ON_BEHALF


class StaffCartView(Guarded):
    @extend_schema(
        operation_id="retailer_cart_retrieve",
        tags=TAGS,
        parameters=[ADDRESS],
        responses=QuoteSerializer,
    )
    def get(self, request: Request, retailer_id: UUID) -> Response:
        return _cart_response(request, shop_for(request, retailer_id))

    @extend_schema(operation_id="retailer_cart_clear", tags=TAGS, responses=QuoteSerializer)
    def delete(self, request: Request, retailer_id: UUID) -> Response:
        retailer = shop_for(request, retailer_id)
        carts.clear(carts.cart_for(retailer, _user(request)))
        return _cart_response(request, retailer)


class StaffCartLineView(Guarded):
    @extend_schema(
        operation_id="retailer_cart_line_set",
        tags=TAGS,
        request=QuantitySerializer,
        responses=QuoteSerializer,
        parameters=[ADDRESS],
    )
    def put(self, request: Request, retailer_id: UUID, product_id: UUID) -> Response:
        data = QuantitySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        retailer = shop_for(request, retailer_id)
        carts.set_quantity(
            carts.cart_for(retailer, _user(request)), product_id, data.validated_data["quantity"]
        )
        return _cart_response(request, retailer)

    @extend_schema(
        operation_id="retailer_cart_line_remove",
        tags=TAGS,
        responses=QuoteSerializer,
        parameters=[ADDRESS],
    )
    def delete(self, request: Request, retailer_id: UUID, product_id: UUID) -> Response:
        retailer = shop_for(request, retailer_id)
        carts.set_quantity(carts.cart_for(retailer, _user(request)), product_id, Decimal("0"))
        return _cart_response(request, retailer)


class StaffCartReduceView(Guarded):
    @extend_schema(
        operation_id="retailer_cart_reduce_to_available",
        tags=TAGS,
        request=None,
        responses=QuoteSerializer,
        parameters=[ADDRESS],
    )
    def post(self, request: Request, retailer_id: UUID) -> Response:
        retailer = shop_for(request, retailer_id)
        carts.reduce_to_available(carts.cart_for(retailer, _user(request)))
        return _cart_response(request, retailer)
