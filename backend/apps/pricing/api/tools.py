"""API for the per-shop pricing tools (ADR-037): permission → serializer → apps.pricing.tools."""

from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import generics, serializers
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.models import User
from apps.catalog.api.serializers import RefSerializer, WarningSerializer
from apps.dataio import services as dataio
from apps.dataio.api.views import FILE
from apps.pricing import tools
from apps.pricing.api.serializers import (
    AppliedDiscountSerializer,
    ProductRefSerializer,
    money,
    qty,
)
from apps.pricing.api.views import VIEW, PricingView, _fake
from apps.pricing.models import DiscountRule, PriceList
from apps.retailers.models import Retailer
from apps.retailers.selectors import RetailerFilters, retailer_for, retailers_for
from common.errors import NotFound

MANAGE = "pricing.manage"


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


def _shop(request: Request, retailer_id: UUID) -> Retailer:
    retailer = retailer_for(_user(request), retailer_id)
    if retailer is None:
        raise NotFound()
    return retailer


def _warnings(items: list[Any]) -> list[dict[str, Any]]:
    return [{"code": w.code, "message": w.message, "details": w.details} for w in items]


class ByName(CursorPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    ordering = ("name", "id")


# --- Serializers ---------------------------------------------------------------------------------


class RuleBriefSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    discount_type = serializers.CharField()
    value = money()
    is_active = serializers.BooleanField()


class GridPriceSerializer(serializers.Serializer[Any]):
    """The server-worked price at the minimum order quantity."""

    qty = qty()
    unit_price = money()
    price_source = serializers.CharField()
    discounts = AppliedDiscountSerializer(many=True)
    discount_total = money()
    discount_percent = serializers.DecimalField(max_digits=6, decimal_places=2)
    net_unit_price = money()


class GridRowSerializer(serializers.Serializer[Any]):
    product = ProductRefSerializer()
    brand = RefSerializer(source="product.brand", allow_null=True)
    category = RefSerializer(source="product.category", allow_null=True)
    simple = RuleBriefSerializer(allow_null=True, help_text="The grid's rule for this pair.")
    others = RuleBriefSerializer(many=True, help_text="Slab or dated rules (read-only here).")
    price = GridPriceSerializer(source="result")


class GridQuerySerializer(serializers.Serializer[Any]):
    search = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    category = serializers.UUIDField(required=False, allow_null=True, default=None)
    brand = serializers.UUIDField(required=False, allow_null=True, default=None)


class GridItemSerializer(serializers.Serializer[Any]):
    product = serializers.UUIDField()
    discount_type = serializers.ChoiceField(choices=DiscountRule.Type.choices)
    value = money(allow_null=True, help_text="Empty or 0 removes the shop's discount.")


class GridItemsSerializer(serializers.Serializer[Any]):
    items = serializers.ListField(child=GridItemSerializer(), min_length=1, max_length=500)


class GridPreviewRowSerializer(serializers.Serializer[Any]):
    product = ProductRefSerializer()
    price = GridPriceSerializer()


class ChangedSerializer(serializers.Serializer[Any]):
    changed = serializers.IntegerField()
    warnings = WarningSerializer(many=True)


class CopySerializer(serializers.Serializer[Any]):
    copy_from = serializers.UUIDField(help_text="The shop whose pricing is copied.")
    # No default: the user chooses every time (ADR-037 item 3).
    mode = serializers.ChoiceField(
        choices=tools.COPY_MODE_CHOICES,
        error_messages={"required": "Choose “Replace” or “Add”."},
    )


class CopyApplySerializer(CopySerializer):
    expected_changes = serializers.IntegerField(min_value=0)


class PriceChangeSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    name = serializers.CharField()
    old = money(allow_null=True)
    new = money()


class CopyPlanSerializer(serializers.Serializer[Any]):
    price_list_from = serializers.CharField(allow_null=True)
    price_list_to = serializers.CharField(allow_null=True)
    price_list_changes = serializers.BooleanField()
    prices_add = PriceChangeSerializer(many=True)
    prices_update = PriceChangeSerializer(many=True)
    prices_remove = PriceChangeSerializer(many=True)
    rules_add = serializers.ListField(child=serializers.CharField())
    rules_replace = serializers.ListField(child=serializers.CharField())
    rules_remove = serializers.ListField(child=serializers.CharField())
    changes = serializers.IntegerField()


def _plan_data(plan: tools.CopyPlan) -> dict[str, Any]:
    return dict(
        CopyPlanSerializer(
            {
                "price_list_from": plan.price_list[0] if plan.price_list else None,
                "price_list_to": plan.price_list[1] if plan.price_list else None,
                "price_list_changes": plan.price_list is not None,
                "prices_add": [
                    {"code": c, "name": n, "old": None, "new": p} for c, n, p in plan.prices_add
                ],
                "prices_update": [
                    {"code": c, "name": n, "old": o, "new": p} for c, n, o, p in plan.prices_update
                ],
                "prices_remove": [
                    {"code": c, "name": n, "old": p, "new": p} for c, n, p in plan.prices_remove
                ],
                "rules_add": plan.rules_add,
                "rules_replace": plan.rules_replace,
                "rules_remove": plan.rules_remove,
                "changes": plan.changes,
            }
        ).data
    )


class AdjustSerializer(serializers.Serializer[Any]):
    percent = serializers.DecimalField(max_digits=7, decimal_places=2)
    category = serializers.UUIDField(required=False, allow_null=True, default=None)
    brand = serializers.UUIDField(required=False, allow_null=True, default=None)
    include_missing = serializers.BooleanField(required=False, default=False)
    rounding = serializers.ChoiceField(choices=["PAISA", "RUPEE"], required=False, default="PAISA")

    def adjustment(self) -> tools.Adjustment:
        v = self.validated_data
        return tools.Adjustment(
            percent=v["percent"],
            category_id=v["category"],
            brand_id=v["brand"],
            include_missing=v["include_missing"],
            whole_rupees=v["rounding"] == "RUPEE",
        )


class AdjustApplySerializer(AdjustSerializer):
    expected_count = serializers.IntegerField(min_value=0)


class AdjustPreviewSerializer(serializers.Serializer[Any]):
    count = serializers.IntegerField()
    added = serializers.IntegerField()
    rows = PriceChangeSerializer(many=True, help_text="The first 200 changes.")


class AdjustResultSerializer(serializers.Serializer[Any]):
    changed = serializers.IntegerField()
    warnings = WarningSerializer(many=True)


class ReportQuerySerializer(serializers.Serializer[Any]):
    search = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    show = serializers.ChoiceField(
        choices=["CUSTOMISED", "ALL"], required=False, default="CUSTOMISED"
    )


class ReportRowSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    code = serializers.CharField()
    shop_name = serializers.CharField()
    price_list = RefSerializer(allow_null=True)
    special_price_count = serializers.IntegerField()
    shop_rule_count = serializers.IntegerField()
    free_product_count = serializers.SerializerMethodField()

    @extend_schema_field(serializers.IntegerField())
    def get_free_product_count(self, shop: Retailer) -> int:
        return len(tools.free_products(shop))


class FreeProductSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    code = serializers.CharField()
    name = serializers.CharField()


# --- Views ---------------------------------------------------------------------------------------


class DiscountGridView(PricingView):
    """GET the grid (pricing.view); PUT saves the shop's per-product discounts (pricing.manage)."""

    required_permissions = {"GET": VIEW, "PUT": MANAGE}
    pagination_class = ByName

    @extend_schema(
        parameters=[GridQuerySerializer, OpenApiParameter("cursor", str, required=False)],
        responses=GridRowSerializer(many=True),
        operation_id="retailers_discount_grid",
        tags=["pricing"],
    )
    def get(self, request: Request, retailer_id: UUID) -> Response:
        retailer = _shop(request, retailer_id)
        query = GridQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        v = query.validated_data
        qs = tools.sellable_products(
            search=v["search"], category_id=v["category"], brand_id=v["brand"]
        ).order_by("name", "id")
        paginator = ByName()
        page = paginator.paginate_queryset(qs, request, view=self) or []
        rows = tools.discount_grid(retailer, list(page))
        return paginator.get_paginated_response(GridRowSerializer(rows, many=True).data)

    @extend_schema(
        request=GridItemsSerializer,
        responses=ChangedSerializer,
        operation_id="retailers_discount_grid_save",
        tags=["pricing"],
    )
    def put(self, request: Request, retailer_id: UUID) -> Response:
        retailer = _shop(request, retailer_id)
        data = GridItemsSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        changed, warnings = tools.save_grid(
            retailer.pk, _items(data.validated_data["items"]), by=_user(request)
        )
        return Response({"changed": changed, "warnings": _warnings(warnings)})


def _items(rows: list[dict[str, Any]]) -> list[tools.GridItem]:
    return [tools.GridItem(r["product"], r["discount_type"], r["value"]) for r in rows]


class DiscountGridPreviewView(PricingView):
    required_permissions = {"POST": VIEW}  # nothing is saved

    @extend_schema(
        request=GridItemsSerializer,
        responses=GridPreviewRowSerializer(many=True),
        operation_id="retailers_discount_grid_preview",
        tags=["pricing"],
    )
    def post(self, request: Request, retailer_id: UUID) -> Response:
        retailer = _shop(request, retailer_id)
        data = GridItemsSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        rows = tools.preview_grid(retailer, _items(data.validated_data["items"]))
        payload = [{"product": p, "price": r} for p, r in rows]
        return Response(GridPreviewRowSerializer(payload, many=True).data)


class CopyPricingPreviewView(PricingView):
    required_permissions = {"POST": MANAGE}

    @extend_schema(
        request=CopySerializer,
        responses=CopyPlanSerializer,
        operation_id="retailers_copy_pricing_preview",
        tags=["pricing"],
    )
    def post(self, request: Request, retailer_id: UUID) -> Response:
        target = _shop(request, retailer_id)
        data = CopySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        source = retailer_for(_user(request), data.validated_data["copy_from"])
        if source is None:
            raise NotFound()
        return Response(_plan_data(tools.plan_copy(source, target, data.validated_data["mode"])))


class CopyPricingView(PricingView):
    required_permissions = {"POST": MANAGE}

    @extend_schema(
        request=CopyApplySerializer,
        responses=CopyPlanSerializer,
        operation_id="retailers_copy_pricing",
        tags=["pricing"],
    )
    def post(self, request: Request, retailer_id: UUID) -> Response:
        target = _shop(request, retailer_id)
        data = CopyApplySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        if retailer_for(_user(request), v["copy_from"]) is None:
            raise NotFound()
        plan = tools.copy_pricing(
            v["copy_from"],
            target.pk,
            v["mode"],
            expected_changes=v["expected_changes"],
            by=_user(request),
        )
        return Response(_plan_data(plan))


def _price_list(price_list_id: UUID) -> PriceList:
    found: PriceList | None = PriceList.objects.filter(
        pk=price_list_id, deleted_at__isnull=True
    ).first()
    if found is None:
        raise NotFound()
    return found


class PriceListAdjustPreviewView(PricingView):
    required_permissions = {"POST": MANAGE}

    @extend_schema(
        request=AdjustSerializer,
        responses=AdjustPreviewSerializer,
        operation_id="price_lists_adjust_preview",
        tags=["pricing"],
    )
    def post(self, request: Request, price_list_id: UUID) -> Response:
        price_list = _price_list(price_list_id)
        data = AdjustSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        rows = tools.plan_adjustment(price_list, data.adjustment())
        return Response(
            {
                "count": len(rows),
                "added": sum(1 for r in rows if r.old is None),
                "rows": PriceChangeSerializer(
                    [
                        {"code": r.code, "name": r.name, "old": r.old, "new": r.new}
                        for r in rows[:200]
                    ],
                    many=True,
                ).data,
            }
        )


class PriceListAdjustView(PricingView):
    required_permissions = {"POST": MANAGE}

    @extend_schema(
        request=AdjustApplySerializer,
        responses=AdjustResultSerializer,
        operation_id="price_lists_adjust",
        tags=["pricing"],
    )
    def post(self, request: Request, price_list_id: UUID) -> Response:
        _price_list(price_list_id)
        data = AdjustApplySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        rows, warnings = tools.adjust_price_list(
            price_list_id,
            data.adjustment(),
            expected_count=data.validated_data["expected_count"],
            by=_user(request),
        )
        return Response({"changed": len(rows), "warnings": _warnings(warnings)})


class ShopPricingReportView(PricingView, generics.ListAPIView[Retailer]):
    """Shops with special prices or shop-specific rules, and the products each gets free."""

    required_permissions = {"GET": VIEW}
    serializer_class = ReportRowSerializer
    pagination_class = type("ReportPages", (ByName,), {"page_size": 25, "ordering": ("code", "id")})
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[Retailer]:
        fake = _fake(self, Retailer)
        if fake is not None:
            return fake
        query = ReportQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        shops = retailers_for(
            _user(self.request), RetailerFilters(search=query.validated_data["search"])
        )
        return tools.shop_pricing_report(
            shops, customised_only=query.validated_data["show"] == "CUSTOMISED"
        )

    @extend_schema(
        parameters=[ReportQuerySerializer],
        operation_id="pricing_shop_report",
        tags=["pricing"],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class ShopPricingReportExportView(PricingView):
    required_permissions = {"GET": VIEW}

    @extend_schema(
        responses={200: FILE},
        operation_id="pricing_shop_report_export",
        tags=["pricing"],
    )
    def get(self, request: Request) -> HttpResponse:
        shops = tools.shop_pricing_report(retailers_for(_user(request))).order_by("code")
        rows: list[list[Any]] = [
            [
                "Shop code",
                "Shop",
                "Price list",
                "Special prices",
                "Shop discount rules",
                "Free products",
            ],
        ]
        for shop in shops:
            rows.append(
                [
                    shop.code,
                    shop.shop_name,
                    shop.price_list.name if shop.price_list else "",
                    shop.special_price_count,  # type: ignore[attr-defined]
                    shop.shop_rule_count,  # type: ignore[attr-defined]
                    len(tools.free_products(shop)),
                ]
            )
        data = dataio.spreadsheet(rows, [14, 30, 18, 14, 18, 14])
        response = HttpResponse(data, content_type=dataio.XLSX)
        response["Content-Disposition"] = 'attachment; filename="shop-pricing.xlsx"'
        return response


class FreeProductsView(PricingView):
    required_permissions = {"GET": VIEW}

    @extend_schema(
        responses=FreeProductSerializer(many=True),
        operation_id="retailers_free_products",
        tags=["pricing"],
    )
    def get(self, request: Request, retailer_id: UUID) -> Response:
        products = tools.free_products(_shop(request, retailer_id))
        return Response(FreeProductSerializer(products, many=True).data)
