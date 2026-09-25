"""Pricing API (PLAN §3.6): reads ``pricing.view``, changes ``pricing.manage`` (audited)."""

from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.pricing import selectors, services
from apps.pricing.api import serializers as s
from apps.pricing.models import DiscountRule, PriceList, PriceListItem, RetailerPrice
from apps.retailers.selectors import retailer_for
from common.errors import NotFound
from common.pagination import DefaultCursorPagination
from common.permissions import HasPermission

VIEW, MANAGE = "pricing.view", "pricing.manage"
READ_WRITE = {"GET": VIEW, "POST": MANAGE, "PUT": MANAGE, "PATCH": MANAGE, "DELETE": MANAGE}


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


class PricingView(APIView):
    permission_classes = [HasPermission]
    required_permissions = READ_WRITE


class Paged(CursorPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500


class ByName(Paged):
    ordering = ("name", "id")


class ByProduct(Paged):
    ordering = ("product__code", "id")


def _fake(view: Any, model: Any) -> QuerySet[Any] | None:
    return model.objects.unscoped().none() if getattr(view, "swagger_fake_view", False) else None


def _price_list_detail(price_list_id: UUID) -> dict[str, Any]:
    found = selectors.price_list(price_list_id)
    if found is None:
        raise NotFound()
    return dict(s.PriceListSerializer(found).data)


class PriceListListCreateView(PricingView, generics.ListAPIView[PriceList]):
    serializer_class = s.PriceListSerializer
    pagination_class = ByName
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[PriceList]:
        return _fake(self, PriceList) or selectors.price_lists()

    @extend_schema(operation_id="price_lists_list", tags=["pricing"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.PriceListWriteSerializer,
        responses={201: s.PriceListSerializer},
        operation_id="price_lists_create",
        tags=["pricing"],
    )
    def post(self, request: Request) -> Response:
        data = s.PriceListWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        created = services.save_price_list(None, **data.validated_data, by=_user(request))
        return Response(_price_list_detail(created.pk), status=201)


class PriceListDetailView(PricingView):
    @extend_schema(
        responses=s.PriceListSerializer, operation_id="price_lists_retrieve", tags=["pricing"]
    )
    def get(self, request: Request, price_list_id: UUID) -> Response:
        return Response(_price_list_detail(price_list_id))

    @extend_schema(
        request=s.PriceListWriteSerializer,
        responses=s.PriceListSerializer,
        operation_id="price_lists_update",
        tags=["pricing"],
    )
    def patch(self, request: Request, price_list_id: UUID) -> Response:
        data = s.PriceListWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.save_price_list(price_list_id, **data.validated_data, by=_user(request))
        return Response(_price_list_detail(price_list_id))

    @extend_schema(
        request=None, responses={204: None}, operation_id="price_lists_delete", tags=["pricing"]
    )
    def delete(self, request: Request, price_list_id: UUID) -> Response:
        services.delete_price_list(price_list_id, by=_user(request))
        return Response(status=204)


class PriceListItemsView(PricingView, generics.ListAPIView[PriceListItem]):
    serializer_class = s.PriceListItemSerializer
    pagination_class = ByProduct
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[PriceListItem]:
        fake = _fake(self, PriceListItem)
        if fake is not None:
            return fake
        price_list_id = self.kwargs["price_list_id"]
        if selectors.price_list(price_list_id) is None:
            raise NotFound()
        return selectors.price_list_items(
            price_list_id, self.request.query_params.get("search", "")
        )

    @extend_schema(
        parameters=[OpenApiParameter("search", str, required=False)],
        operation_id="price_list_items_list",
        tags=["pricing"],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.ItemsUpsertSerializer,
        responses=s.ItemsUpsertResultSerializer,
        operation_id="price_list_items_upsert",
        tags=["pricing"],
    )
    def put(self, request: Request, price_list_id: UUID) -> Response:
        data = s.ItemsUpsertSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        changed = services.upsert_items(
            price_list_id,
            [services.ItemInput(i["product"], i["price"]) for i in data.validated_data["items"]],
            by=_user(request),
        )
        return Response({"changed": changed})


class PriceListItemDetailView(PricingView):
    @extend_schema(
        request=None,
        responses={204: None},
        operation_id="price_list_items_delete",
        tags=["pricing"],
    )
    def delete(self, request: Request, price_list_id: UUID, product_id: UUID) -> Response:
        services.delete_item(price_list_id, product_id, by=_user(request))
        return Response(status=204)


class RetailerPriceListCreateView(PricingView, generics.ListAPIView[RetailerPrice]):
    serializer_class = s.RetailerPriceSerializer
    pagination_class = DefaultCursorPagination
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[RetailerPrice]:
        fake = _fake(self, RetailerPrice)
        if fake is not None:
            return fake
        f = s.RetailerPriceFilterSerializer(data=self.request.query_params)
        f.is_valid(raise_exception=True)
        return selectors.retailer_prices(
            _user(self.request),
            retailer_id=f.validated_data.get("retailer"),
            product_id=f.validated_data.get("product"),
        )

    @extend_schema(
        parameters=[s.RetailerPriceFilterSerializer],
        operation_id="retailer_prices_list",
        tags=["pricing"],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.RetailerPriceWriteSerializer,
        responses={201: s.RetailerPriceSerializer},
        operation_id="retailer_prices_create",
        tags=["pricing"],
    )
    def post(self, request: Request) -> Response:
        data = s.RetailerPriceWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        if retailer_for(_user(request), v["retailer"]) is None:
            v["retailer"] = None  # another tenant's or a hidden shop: "choose an existing shop"
        row = services.save_retailer_price(
            None,
            retailer_id=v["retailer"],
            product_id=v["product"],
            price=v["price"],
            note=v["note"],
            by=_user(request),
        )
        return Response(s.RetailerPriceSerializer(row).data, status=201)


class RetailerPriceDetailView(PricingView):
    def _row(self, request: Request, price_id: UUID) -> RetailerPrice:
        row = selectors.retailer_prices(_user(request)).filter(pk=price_id).first()
        if row is None:
            raise NotFound()
        return row

    @extend_schema(
        request=s.RetailerPriceUpdateSerializer,
        responses=s.RetailerPriceSerializer,
        operation_id="retailer_prices_update",
        tags=["pricing"],
    )
    def patch(self, request: Request, price_id: UUID) -> Response:
        self._row(request, price_id)
        data = s.RetailerPriceUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = services.save_retailer_price(
            price_id,
            price=data.validated_data["price"],
            note=data.validated_data["note"],
            by=_user(request),
        )
        return Response(s.RetailerPriceSerializer(row).data)

    @extend_schema(
        request=None, responses={204: None}, operation_id="retailer_prices_delete", tags=["pricing"]
    )
    def delete(self, request: Request, price_id: UUID) -> Response:
        self._row(request, price_id)
        services.delete_retailer_price(price_id, by=_user(request))
        return Response(status=204)


def _slabs(data: dict[str, Any]) -> list[services.SlabInput]:
    return [services.SlabInput(x["min_qty"], x["value"]) for x in data.get("slabs", [])]


class DiscountRuleListCreateView(PricingView, generics.ListAPIView[DiscountRule]):
    serializer_class = s.DiscountRuleSerializer
    pagination_class = ByName
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[DiscountRule]:
        fake = _fake(self, DiscountRule)
        if fake is not None:
            return fake
        f = s.DiscountRuleFilterSerializer(data=self.request.query_params)
        f.is_valid(raise_exception=True)
        return selectors.discount_rules(active=f.validated_data["active"])

    @extend_schema(
        parameters=[s.DiscountRuleFilterSerializer],
        operation_id="discount_rules_list",
        tags=["pricing"],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.DiscountRuleWriteSerializer,
        responses={201: s.DiscountRuleSerializer},
        operation_id="discount_rules_create",
        tags=["pricing"],
    )
    def post(self, request: Request) -> Response:
        data = s.DiscountRuleWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        rule = services.save_discount_rule(
            None,
            s.rule_fields(dict(data.validated_data)),
            _slabs(data.validated_data),
            by=_user(request),
        )
        return Response(
            s.DiscountRuleSerializer(selectors.discount_rules().get(pk=rule.pk)).data, status=201
        )


class DiscountRuleDetailView(PricingView):
    @extend_schema(
        responses=s.DiscountRuleSerializer, operation_id="discount_rules_retrieve", tags=["pricing"]
    )
    def get(self, request: Request, rule_id: UUID) -> Response:
        rule = selectors.discount_rules().filter(pk=rule_id).first()
        if rule is None:
            raise NotFound()
        return Response(s.DiscountRuleSerializer(rule).data)

    @extend_schema(
        request=s.DiscountRuleWriteSerializer,
        responses=s.DiscountRuleSerializer,
        operation_id="discount_rules_update",
        tags=["pricing"],
    )
    def patch(self, request: Request, rule_id: UUID) -> Response:
        data = s.DiscountRuleWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        slabs = _slabs(data.validated_data) if "slabs" in request.data else None
        services.save_discount_rule(
            rule_id, s.rule_fields(dict(data.validated_data)), slabs, by=_user(request)
        )
        return Response(s.DiscountRuleSerializer(selectors.discount_rules().get(pk=rule_id)).data)

    @extend_schema(
        request=None, responses={204: None}, operation_id="discount_rules_delete", tags=["pricing"]
    )
    def delete(self, request: Request, rule_id: UUID) -> Response:
        services.delete_discount_rule(rule_id, by=_user(request))
        return Response(status=204)
