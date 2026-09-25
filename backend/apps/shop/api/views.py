"""Retailer app catalog (PLAN §3.9, task 2.13): thin views over ``apps.shop.selectors``.

Only RETAILER logins get in, and every query is scoped to the login's own shop (``_retailer``)
inside its distributor's tenant (the tenant comes from the token, as everywhere).
"""

from typing import Any
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.retailers.models import Retailer
from apps.retailers.selectors import own_retailer
from apps.shop import selectors
from apps.shop.api import serializers as s
from common.errors import NotFound
from common.permissions import IsRetailer


def _retailer(request: Request) -> Retailer:
    user: User = request.user  # type: ignore[assignment]
    retailer = own_retailer(user)
    if retailer is None:
        raise PermissionDenied()
    return retailer


class ShopView(APIView):
    permission_classes = [IsRetailer]


class ByName(CursorPagination):
    page_size = 30
    page_size_query_param = "page_size"
    max_page_size = 60
    ordering = ("name", "id")


class _ProductQuery(serializers.Serializer[Any]):
    search = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    category = serializers.UUIDField(required=False, allow_null=True, default=None)
    brand = serializers.UUIDField(required=False, allow_null=True, default=None)


class ShopCategoriesView(ShopView):
    @extend_schema(
        operation_id="shop_categories",
        tags=["shop"],
        responses=s.ShopCategorySerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        tree = selectors.shop_category_tree(_retailer(request))
        return Response(s.ShopCategorySerializer(tree, many=True).data)


class ShopBrandsView(ShopView):
    @extend_schema(
        operation_id="shop_brands",
        tags=["shop"],
        parameters=[OpenApiParameter("category", UUID, required=False)],
        responses=s.ShopBrandSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        query = _ProductQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        brands = selectors.shop_brands(_retailer(request), query.validated_data["category"])
        return Response(s.ShopBrandSerializer(brands, many=True).data)


class ShopProductsView(ShopView):
    """Browse by name (paged), or search: the best ``SEARCH_LIMIT`` matches on one page."""

    pagination_class = ByName

    @extend_schema(
        operation_id="shop_products",
        tags=["shop"],
        parameters=[
            OpenApiParameter("search", str, required=False),
            OpenApiParameter("category", UUID, required=False),
            OpenApiParameter("brand", UUID, required=False),
            OpenApiParameter("cursor", str, required=False),
            OpenApiParameter("page_size", int, required=False),
        ],
        responses=s.ShopProductSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        query = _ProductQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        retailer = _retailer(request)
        filters = selectors.ShopFilters(
            search=query.validated_data["search"],
            category_id=query.validated_data["category"],
            brand_id=query.validated_data["brand"],
        )
        qs = selectors.shop_products(retailer, filters)
        paginator = ByName()
        if filters.search.strip():
            page = list(qs[: selectors.SEARCH_LIMIT])
            rows = self._rows(retailer, page)
            return Response({"next": None, "previous": None, "results": rows})
        page = paginator.paginate_queryset(qs, request, view=self) or []
        return paginator.get_paginated_response(self._rows(retailer, page))

    @staticmethod
    def _rows(retailer: Retailer, page: list[Any]) -> list[Any]:
        rows = [{"product": p, "price": r} for p, r in selectors.priced(retailer, page)]
        return list(s.ShopProductSerializer(rows, many=True).data)


class ShopProductDetailView(ShopView):
    @extend_schema(
        operation_id="shop_product", tags=["shop"], responses=s.ShopProductDetailSerializer
    )
    def get(self, request: Request, product_id: UUID) -> Response:
        found = selectors.shop_product(_retailer(request), product_id)
        if found is None:
            raise NotFound()
        row = {"product": found.product, "price": found.price, "slab_hints": found.slab_hints}
        return Response(s.ShopProductDetailSerializer(row).data)
