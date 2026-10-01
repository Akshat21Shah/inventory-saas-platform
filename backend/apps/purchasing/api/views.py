from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.purchasing import selectors, services
from apps.purchasing.api import serializers as s
from apps.purchasing.models import Supplier, SupplierProduct
from common.errors import NotFound
from common.permissions import FeatureOn, HasPermission

VIEW = "purchasing.view"
MANAGE = "purchasing.manage"
READ_WRITE = {"GET": VIEW, "POST": MANAGE, "PUT": MANAGE, "PATCH": MANAGE, "DELETE": MANAGE}


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


def _costs(request: Request) -> bool:
    return _user(request).has_permission_code("costs.view")


class PurchasingView(APIView):
    permission_classes = [HasPermission, FeatureOn]
    required_feature = "purchasing"
    required_permissions = READ_WRITE


class NamePagination(CursorPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100
    ordering = ("name", "id")


class SupplierListCreateView(PurchasingView, generics.ListAPIView[Supplier]):
    serializer_class = s.SupplierListSerializer
    pagination_class = NamePagination
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[Supplier]:
        if getattr(self, "swagger_fake_view", False):
            return Supplier.objects.unscoped().none()
        f = s.SupplierFilterSerializer(data=self.request.query_params)
        f.is_valid(raise_exception=True)
        return selectors.suppliers(
            search=f.validated_data["search"], active=f.validated_data["active"]
        )

    @extend_schema(
        parameters=[s.SupplierFilterSerializer], operation_id="suppliers_list", tags=["purchasing"]
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.SupplierWriteSerializer,
        responses={201: s.SupplierDetailSerializer},
        operation_id="suppliers_create",
        tags=["purchasing"],
    )
    def post(self, request: Request) -> Response:
        data = s.SupplierWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        supplier = services.create_supplier(data.to_service(), by=_user(request))
        return Response(_detail(supplier.pk), status=201)


def _detail(supplier_id: UUID) -> Any:
    supplier = selectors.supplier(supplier_id)
    if supplier is None:
        raise NotFound()
    return s.SupplierDetailSerializer(supplier).data


class SupplierDetailView(PurchasingView):
    @extend_schema(
        responses=s.SupplierDetailSerializer, operation_id="suppliers_get", tags=["purchasing"]
    )
    def get(self, request: Request, supplier_id: UUID) -> Response:
        return Response(_detail(supplier_id))

    @extend_schema(
        request=s.SupplierWriteSerializer(partial=True),
        responses=s.SupplierDetailSerializer,
        operation_id="suppliers_update",
        tags=["purchasing"],
    )
    def patch(self, request: Request, supplier_id: UUID) -> Response:
        data = s.SupplierWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        services.update_supplier(supplier_id, data.to_service(), by=_user(request))
        return Response(_detail(supplier_id))

    @extend_schema(
        request=None, responses={204: None}, operation_id="suppliers_delete", tags=["purchasing"]
    )
    def delete(self, request: Request, supplier_id: UUID) -> Response:
        services.delete_supplier(supplier_id, by=_user(request))
        return Response(status=204)


class ProductCodePagination(CursorPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    ordering = ("product__code", "id")


class SupplierProductsView(PurchasingView, generics.ListAPIView[SupplierProduct]):
    """What a supplier supplies; POST makes it the preferred supplier for the products given
    (the products list's bulk action)."""

    serializer_class = s.SupplierProductSerializer
    pagination_class = ProductCodePagination
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[SupplierProduct]:
        if getattr(self, "swagger_fake_view", False):
            return SupplierProduct.objects.unscoped().none()
        supplier = selectors.supplier(self.kwargs["supplier_id"])
        if supplier is None:
            raise NotFound()
        return SupplierProduct.objects.filter(
            supplier=supplier, product__deleted_at__isnull=True
        ).select_related("supplier", "product")

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "costs": _costs(self.request)}

    @extend_schema(operation_id="supplier_products_list", tags=["purchasing"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.SetPreferredSerializer,
        responses=s.PreferredChangedSerializer,
        operation_id="supplier_products_set_preferred",
        tags=["purchasing"],
    )
    def post(self, request: Request, supplier_id: UUID) -> Response:
        data = s.SetPreferredSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        changed = services.set_preferred_supplier(
            supplier_id, data.validated_data["product_ids"], by=_user(request)
        )
        return Response({"changed": changed})


class ProductSuppliersView(PurchasingView):
    """Who a product is bought from: codes, delivery times, packs and the last cost (with
    ``costs.view``)."""

    def _rows(self, request: Request, product_id: UUID) -> Any:
        rows = selectors.product_suppliers(product_id).select_related("product")
        return s.SupplierProductSerializer(rows, many=True, context={"costs": _costs(request)}).data

    @extend_schema(
        responses=s.SupplierProductSerializer(many=True),
        operation_id="product_suppliers_list",
        tags=["purchasing"],
    )
    def get(self, request: Request, product_id: UUID) -> Response:
        if not selectors.product_exists(product_id):
            raise NotFound()
        return Response(self._rows(request, product_id))

    @extend_schema(
        request=s.ProductSuppliersSerializer,
        responses=s.SupplierProductSerializer(many=True),
        operation_id="product_suppliers_set",
        tags=["purchasing"],
    )
    def put(self, request: Request, product_id: UUID) -> Response:
        data = s.ProductSuppliersSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        links = [services.LinkInput(**link) for link in data.validated_data["links"]]
        services.set_product_suppliers(product_id, links, by=_user(request))
        return Response(self._rows(request, product_id))


class ReceiptSuppliersView(PurchasingView):
    """The one-time review of supplier names typed on past goods receipts."""

    required_permissions = {"GET": MANAGE, "POST": MANAGE}

    @extend_schema(
        responses=s.ReceiptSupplierNameSerializer(many=True),
        operation_id="suppliers_from_receipts",
        tags=["purchasing"],
    )
    def get(self, request: Request) -> Response:
        rows = selectors.receipt_supplier_names()
        return Response(s.ReceiptSupplierNameSerializer(rows, many=True).data)

    @extend_schema(
        request=s.ConfirmReceiptSuppliersSerializer,
        responses=s.ConfirmResultSerializer,
        operation_id="suppliers_from_receipts_confirm",
        tags=["purchasing"],
    )
    def post(self, request: Request) -> Response:
        data = s.ConfirmReceiptSuppliersSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        choices = [
            services.ReceiptSupplierChoice(c["name"], c["supplier_id"], create=c["new"])
            for c in data.validated_data["choices"]
        ]
        return Response(services.confirm_receipt_suppliers(choices, by=_user(request)))
