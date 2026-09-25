"""Catalog API (PLAN §3.5): thin views over ``catalog.services`` and ``catalog.selectors``.
Reads need ``products.view``; every change needs ``products.manage``."""

from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.pagination import CursorPagination
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.catalog import search, selectors, services
from apps.catalog.api import serializers as s
from apps.catalog.models import Brand, Category, Product, Unit
from common.dates import today_ist
from common.errors import NotFound
from common.permissions import HasPermission

VIEW, MANAGE = "products.view", "products.manage"
READ_WRITE = {"GET": VIEW, "POST": MANAGE, "PUT": MANAGE, "PATCH": MANAGE, "DELETE": MANAGE}


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


class CatalogView(APIView):
    permission_classes = [HasPermission]
    required_permissions = READ_WRITE


class NamePagination(CursorPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    ordering = ("name", "id")


class CodePagination(NamePagination):
    ordering = ("code", "id")


def _fake(view: Any, model: Any) -> QuerySet[Any] | None:
    """Schema generation has no tenant: return an empty queryset instead of querying."""
    return model.objects.unscoped().none() if getattr(view, "swagger_fake_view", False) else None


# --- Categories ---------------------------------------------------------------------------------


class CategoryListCreateView(CatalogView, generics.ListAPIView[Category]):
    serializer_class = s.CategorySerializer
    pagination_class = NamePagination
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[Category]:
        return _fake(self, Category) or selectors.categories()

    @extend_schema(operation_id="catalog_categories_list", tags=["catalog"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.CategoryWriteSerializer,
        responses={201: s.CategorySerializer},
        operation_id="catalog_categories_create",
        tags=["catalog"],
    )
    def post(self, request: Request) -> Response:
        data = s.CategoryWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        category = services.create_category(
            name=data.validated_data["name"],
            parent_id=data.validated_data["parent_id"],
            sort_order=data.validated_data["sort_order"],
            by=_user(request),
        )
        return Response(s.CategorySerializer(category).data, status=201)


class CategoryTreeView(CatalogView):
    @extend_schema(
        responses=s.CategoryTreeNodeSerializer(many=True),
        operation_id="catalog_categories_tree",
        tags=["catalog"],
    )
    def get(self, request: Request) -> Response:
        return Response(s.CategoryTreeNodeSerializer(selectors.category_tree(), many=True).data)


class CategoryDetailView(CatalogView):
    @extend_schema(
        responses=s.CategorySerializer, operation_id="catalog_categories_retrieve", tags=["catalog"]
    )
    def get(self, request: Request, category_id: UUID) -> Response:
        category = selectors.category(category_id)
        if category is None:
            raise NotFound()
        return Response(s.CategorySerializer(category).data)

    @extend_schema(
        request=s.CategoryUpdateSerializer,
        responses=s.CategorySerializer,
        operation_id="catalog_categories_update",
        tags=["catalog"],
    )
    def patch(self, request: Request, category_id: UUID) -> Response:
        data = s.CategoryUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        category = services.update_category(
            category_id, dict(data.validated_data), by=_user(request)
        )
        return Response(s.CategorySerializer(category).data)

    @extend_schema(
        request=None,
        responses={204: None},
        operation_id="catalog_categories_delete",
        tags=["catalog"],
    )
    def delete(self, request: Request, category_id: UUID) -> Response:
        services.delete_category(category_id, by=_user(request))
        return Response(status=204)


# --- Brands and units ---------------------------------------------------------------------------


class BrandListCreateView(CatalogView, generics.ListAPIView[Brand]):
    serializer_class = s.BrandSerializer
    pagination_class = NamePagination
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[Brand]:
        qs = _fake(self, Brand) or selectors.brands()
        term = self.request.query_params.get("search", "").strip()
        return qs.filter(name__icontains=term) if term else qs

    @extend_schema(
        parameters=[OpenApiParameter("search", str, required=False)],
        operation_id="catalog_brands_list",
        tags=["catalog"],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.BrandSerializer,
        responses={201: s.BrandSerializer},
        operation_id="catalog_brands_create",
        tags=["catalog"],
    )
    def post(self, request: Request) -> Response:
        data = s.BrandSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        brand = services.save_brand(None, name=data.validated_data["name"], by=_user(request))
        return Response(s.BrandSerializer(brand).data, status=201)


class BrandDetailView(CatalogView):
    @extend_schema(
        request=s.BrandSerializer,
        responses=s.BrandSerializer,
        operation_id="catalog_brands_update",
        tags=["catalog"],
    )
    def patch(self, request: Request, brand_id: UUID) -> Response:
        data = s.BrandSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        brand = services.save_brand(brand_id, name=data.validated_data["name"], by=_user(request))
        return Response(s.BrandSerializer(brand).data)

    @extend_schema(
        request=None, responses={204: None}, operation_id="catalog_brands_delete", tags=["catalog"]
    )
    def delete(self, request: Request, brand_id: UUID) -> Response:
        services.delete_brand(brand_id, by=_user(request))
        return Response(status=204)


class UnitListCreateView(CatalogView, generics.ListAPIView[Unit]):
    serializer_class = s.UnitSerializer
    pagination_class = CodePagination
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[Unit]:
        return _fake(self, Unit) or selectors.units()

    @extend_schema(operation_id="catalog_units_list", tags=["catalog"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.UnitWriteSerializer,
        responses={201: s.UnitSerializer},
        operation_id="catalog_units_create",
        tags=["catalog"],
    )
    def post(self, request: Request) -> Response:
        data = s.UnitWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        unit = services.save_unit(None, dict(data.validated_data), by=_user(request))
        return Response(s.UnitSerializer(unit).data, status=201)


class UnitDetailView(CatalogView):
    @extend_schema(
        request=s.UnitWriteSerializer(partial=True),
        responses=s.UnitSerializer,
        operation_id="catalog_units_update",
        tags=["catalog"],
    )
    def patch(self, request: Request, unit_id: UUID) -> Response:
        data = s.UnitWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        unit = services.save_unit(unit_id, dict(data.validated_data), by=_user(request))
        return Response(s.UnitSerializer(unit).data)

    @extend_schema(
        request=None, responses={204: None}, operation_id="catalog_units_delete", tags=["catalog"]
    )
    def delete(self, request: Request, unit_id: UUID) -> Response:
        services.delete_unit(unit_id, by=_user(request))
        return Response(status=204)


# --- Products -----------------------------------------------------------------------------------


def _detail(product_id: UUID, warnings: list[services.Warning] | None = None) -> dict[str, Any]:
    product = selectors.product(product_id)
    if product is None:
        raise NotFound()
    return dict(s.ProductDetailSerializer(product, context={"warnings": warnings or []}).data)


class ProductListCreateView(CatalogView, generics.ListAPIView[Product]):
    serializer_class = s.ProductListSerializer
    pagination_class = NamePagination
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[Product]:
        fake = _fake(self, Product)
        if fake is not None:
            return fake
        f = s.ProductFilterSerializer(data=self.request.query_params)
        f.is_valid(raise_exception=True)
        v = f.validated_data
        return selectors.product_list(
            selectors.ProductFilters(
                search=v["search"],
                category_id=v.get("category"),
                brand_id=v.get("brand"),
                is_active=v["is_active"],
                show_in_shop=v["show_in_shop"],
                hsn_prefix=v["hsn_prefix"],
            )
        )

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "rates": getattr(self, "_rates", {})}

    def paginate_queryset(self, queryset: Any) -> Any:
        page = super().paginate_queryset(queryset)
        if page is not None:  # the current GST rate of the page's products, in one query
            self._rates = selectors.tax_rates_on([p.pk for p in page])
        return page

    @extend_schema(
        parameters=[s.ProductFilterSerializer],
        operation_id="catalog_products_list",
        tags=["catalog"],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.ProductWriteSerializer,
        responses={201: s.ProductDetailSerializer},
        operation_id="catalog_products_create",
        tags=["catalog"],
    )
    def post(self, request: Request) -> Response:
        data = s.ProductWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = dict(data.validated_data)
        gst_rate, cess_type, cess_rate = v.pop("gst_rate"), v.pop("cess_type"), v.pop("cess_rate")
        barcodes = v.pop("barcodes")
        product, warnings = services.create_product(
            s.to_model_fields(v),
            gst_rate=gst_rate,
            cess_type_id=cess_type,
            cess_rate=cess_rate,
            barcodes=barcodes,
            by=_user(request),
        )
        return Response(_detail(product.pk, warnings), status=201)


class ProductDetailView(CatalogView):
    @extend_schema(
        responses=s.ProductDetailSerializer,
        operation_id="catalog_products_retrieve",
        tags=["catalog"],
    )
    def get(self, request: Request, product_id: UUID) -> Response:
        return Response(_detail(product_id))

    @extend_schema(
        request=s.ProductUpdateSerializer,
        responses=s.ProductDetailSerializer,
        operation_id="catalog_products_update",
        tags=["catalog"],
    )
    def patch(self, request: Request, product_id: UUID) -> Response:
        data = s.ProductUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        product, warnings = services.update_product(
            product_id, s.to_model_fields(dict(data.validated_data)), by=_user(request)
        )
        return Response(_detail(product.pk, warnings))

    @extend_schema(
        request=None,
        responses={204: None},
        operation_id="catalog_products_delete",
        tags=["catalog"],
    )
    def delete(self, request: Request, product_id: UUID) -> Response:
        services.delete_product(product_id, by=_user(request))
        return Response(status=204)


class ProductLookupView(CatalogView):
    @extend_schema(
        parameters=[s.LookupSerializer],
        responses=s.ProductDetailSerializer,
        operation_id="catalog_products_lookup",
        tags=["catalog"],
    )
    def get(self, request: Request) -> Response:
        data = s.LookupSerializer(data=request.query_params)
        data.is_valid(raise_exception=True)
        product = selectors.product_by_code_or_barcode(
            code=data.validated_data["code"], barcode=data.validated_data["barcode"]
        )
        if product is None:
            raise NotFound()
        return Response(_detail(product.pk))


class ProductBulkView(CatalogView):
    @extend_schema(
        request=s.BulkSerializer,
        responses=s.BulkResultSerializer,
        operation_id="catalog_products_bulk",
        tags=["catalog"],
    )
    def post(self, request: Request) -> Response:
        data = s.BulkSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        changed = services.bulk_update(
            data.validated_data["product_ids"],
            data.validated_data["action"],
            value=data.validated_data["value"],
            by=_user(request),
        )
        return Response({"changed": changed})


class ProductBarcodesView(CatalogView):
    @extend_schema(
        request=s.BarcodeSerializer,
        responses={201: s.BarcodeSerializer},
        operation_id="catalog_product_barcodes_create",
        tags=["catalog"],
    )
    def post(self, request: Request, product_id: UUID) -> Response:
        data = s.BarcodeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = services.add_barcode(product_id, data.validated_data["barcode"], by=_user(request))
        return Response(s.BarcodeSerializer(row).data, status=201)


class ProductBarcodeDetailView(CatalogView):
    @extend_schema(
        request=None,
        responses={204: None},
        operation_id="catalog_product_barcodes_delete",
        tags=["catalog"],
    )
    def delete(self, request: Request, product_id: UUID, barcode_id: UUID) -> Response:
        services.remove_barcode(product_id, barcode_id, by=_user(request))
        return Response(status=204)


class ProductTaxRatesView(CatalogView):
    @extend_schema(
        responses=s.ProductTaxRateSerializer(many=True),
        operation_id="catalog_product_tax_rates_list",
        tags=["catalog"],
    )
    def get(self, request: Request, product_id: UUID) -> Response:
        product = selectors.product(product_id)
        if product is None:
            raise NotFound()
        current = selectors.tax_rate_on(product.pk)
        context = {"current_id": current.pk if current else None, "today": today_ist()}
        return Response(
            s.ProductTaxRateSerializer(product.tax_rates.all(), many=True, context=context).data
        )

    @extend_schema(
        request=s.ScheduleRateSerializer,
        responses={201: s.ProductDetailSerializer},
        operation_id="catalog_product_tax_rates_schedule",
        tags=["catalog"],
    )
    def post(self, request: Request, product_id: UUID) -> Response:
        data = s.ScheduleRateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        services.schedule_tax_rate(
            product_id,
            gst_rate=v["gst_rate"],
            effective_from=v["effective_from"],
            cess_type_id=v["cess_type"],
            cess_rate=v["cess_rate"],
            reason=v["reason"],
            by=_user(request),
        )
        return Response(_detail(product_id), status=201)


class ProductTaxRateCancelView(CatalogView):
    @extend_schema(
        request=s.CancelRateSerializer,
        responses=s.ProductDetailSerializer,
        operation_id="catalog_product_tax_rates_cancel",
        tags=["catalog"],
    )
    def post(self, request: Request, product_id: UUID, rate_id: UUID) -> Response:
        data = s.CancelRateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.cancel_tax_rate(
            product_id, rate_id, reason=data.validated_data["reason"], by=_user(request)
        )
        return Response(_detail(product_id))


class TaxRateScheduleView(CatalogView):
    @extend_schema(
        request=s.BulkScheduleSerializer,
        responses=s.BulkScheduleResultSerializer,
        operation_id="catalog_tax_rates_bulk_schedule",
        tags=["catalog"],
    )
    def post(self, request: Request) -> Response:
        data = s.BulkScheduleSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        f = services.RateScheduleFilter(
            hsn_prefix=v["hsn_prefix"],
            category_id=v["category"],
            product_ids=tuple(v["product_ids"]),
        )
        if v["preview"]:
            return Response(
                {**services.preview_rate_schedule(f, v["effective_from"]), "committed": False}
            )
        count = services.commit_rate_schedule(
            f,
            gst_rate=v["gst_rate"],
            effective_from=v["effective_from"],
            expected_count=v.get("expected_count", -1),
            cess_type_id=v["cess_type"],
            cess_rate=v["cess_rate"],
            reason=v["reason"],
            by=_user(request),
        )
        return Response({"count": count, "committed": True})


class TaxOptionsView(CatalogView):
    """The GST rates and percentage cesses in use (platform reference data) for product forms."""

    @extend_schema(
        responses=s.TaxOptionsSerializer, operation_id="catalog_tax_options", tags=["catalog"]
    )
    def get(self, request: Request) -> Response:
        return Response(s.TaxOptionsSerializer(selectors.tax_options()).data)


class HsnHintView(CatalogView):
    @extend_schema(
        parameters=[OpenApiParameter("hsn", str, required=True)],
        responses=s.HsnHintResultSerializer,
        operation_id="catalog_hsn_hint",
        tags=["catalog"],
    )
    def get(self, request: Request) -> Response:
        hint = selectors.hsn_hint("".join(request.query_params.get("hsn", "").split())[:8])
        return Response({"hint": s.HsnSuggestionSerializer(hint).data if hint else None})


class ProductImagesView(CatalogView):
    parser_classes = [MultiPartParser]

    @extend_schema(
        responses=s.ProductImageSerializer(many=True),
        operation_id="catalog_product_images_list",
        tags=["catalog"],
    )
    def get(self, request: Request, product_id: UUID) -> Response:
        product = selectors.product(product_id)
        if product is None:
            raise NotFound()
        return Response(s.ProductImageSerializer(product.images.all(), many=True).data)

    @extend_schema(
        request={"multipart/form-data": s.ImageUploadSerializer},
        responses={201: s.ProductImageSerializer},
        operation_id="catalog_product_images_upload",
        tags=["catalog"],
    )
    def post(self, request: Request, product_id: UUID) -> Response:
        data = s.ImageUploadSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        image = services.upload_image(
            product_id,
            data.validated_data["file"],
            alt_text=data.validated_data["alt_text"],
            by=_user(request),
        )
        return Response(s.ProductImageSerializer(image).data, status=201)


class ProductImageDetailView(CatalogView):
    @extend_schema(
        request=s.ImageUpdateSerializer,
        responses=s.ProductImageSerializer,
        operation_id="catalog_product_images_update",
        tags=["catalog"],
    )
    def patch(self, request: Request, product_id: UUID, image_id: UUID) -> Response:
        data = s.ImageUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        image = services.update_image(
            product_id,
            image_id,
            sort_order=data.validated_data.get("sort_order"),
            alt_text=data.validated_data.get("alt_text"),
            by=_user(request),
        )
        return Response(s.ProductImageSerializer(image).data)

    @extend_schema(
        request=None,
        responses={204: None},
        operation_id="catalog_product_images_delete",
        tags=["catalog"],
    )
    def delete(self, request: Request, product_id: UUID, image_id: UUID) -> Response:
        services.delete_image(product_id, image_id, by=_user(request))
        return Response(status=204)


class ProductSearchView(CatalogView):
    @extend_schema(
        parameters=[OpenApiParameter("q", str, required=True)],
        responses=s.SearchResultSerializer(many=True),
        operation_id="catalog_products_search",
        tags=["catalog"],
    )
    def get(self, request: Request) -> Response:
        """Fast type-ahead: at most 20 best matches (< 200 ms on 20,000 products)."""
        results = search.ranked(selectors.product_list(), request.query_params.get("q", ""))
        return Response(s.SearchResultSerializer(results, many=True).data)
