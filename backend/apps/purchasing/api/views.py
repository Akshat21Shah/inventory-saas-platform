from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import F, QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.billing.api.serializers import DocumentLinkSerializer
from apps.inventory.api.serializers import ReceiptDetailSerializer
from apps.purchasing import orders, receiving, selectors, services
from apps.purchasing.api import serializers as s
from apps.purchasing.models import PurchaseOrder, Supplier, SupplierProduct
from common.errors import NotFound
from common.idempotency import idempotent
from common.pagination import DefaultCursorPagination
from common.permissions import AnyOf, FeatureOn, HasPermission, Requirement

VIEW = "purchasing.view"
MANAGE = "purchasing.manage"
READ_WRITE: dict[str, Requirement] = {
    "GET": VIEW,
    "POST": MANAGE,
    "PUT": MANAGE,
    "PATCH": MANAGE,
    "DELETE": MANAGE,
}


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


def _costs(request: Request) -> bool:
    return _user(request).has_permission_code("costs.view")


class PurchasingView(APIView):
    permission_classes = [HasPermission, FeatureOn]
    required_feature = "purchasing"
    required_permissions: dict[str, Requirement] = READ_WRITE


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
    ordering = ("sort_code", "id")  # an annotation: the cursor reads it from each row


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
        rows: QuerySet[SupplierProduct] = (
            SupplierProduct.objects.filter(supplier=supplier, product__deleted_at__isnull=True)
            .select_related("supplier", "product")
            .annotate(sort_code=F("product__code"))
        )
        return rows

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


# --- Purchase orders ------------------------------------------------------------------------------

IDEMPOTENCY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, True)


def _order_response(request: Request, order_id: UUID, status: int = 200) -> Response:
    order = selectors.purchase_order(order_id)
    if order is None:
        raise NotFound()
    context = {"costs": _costs(request)}
    return Response(s.PurchaseOrderDetailSerializer(order, context=context).data, status=status)


def _order_input(data: dict[str, Any]) -> orders.OrderInput:
    return orders.OrderInput(
        supplier_id=data["supplier_id"],
        expected_date=data["expected_date"],
        notes=data["notes"],
        lines=[orders.OrderLineInput(**line) for line in data["lines"]],
    )


class PurchaseOrderListCreateView(PurchasingView, generics.ListAPIView[PurchaseOrder]):
    serializer_class = s.PurchaseOrderListSerializer
    pagination_class = DefaultCursorPagination
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[PurchaseOrder]:
        if getattr(self, "swagger_fake_view", False):
            return PurchaseOrder.objects.unscoped().none()
        f = s.PurchaseOrderFilterSerializer(data=self.request.query_params)
        f.is_valid(raise_exception=True)
        v = f.validated_data
        return selectors.purchase_orders(
            selectors.OrderFilters(
                status=v["status"], supplier_id=v["supplier"], late=v["late"], search=v["search"]
            )
        )

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "costs": _costs(self.request)}

    @extend_schema(
        parameters=[s.PurchaseOrderFilterSerializer],
        operation_id="purchase_orders_list",
        tags=["purchasing"],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.PurchaseOrderInputSerializer,
        responses={201: s.PurchaseOrderDetailSerializer},
        operation_id="purchase_orders_create",
        tags=["purchasing"],
    )
    def post(self, request: Request) -> Response:
        data = s.PurchaseOrderInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        order = orders.create_order(_order_input(data.validated_data), by=_user(request))
        return _order_response(request, order.pk, status=201)


class PurchaseOrderDetailView(PurchasingView):
    @extend_schema(
        responses=s.PurchaseOrderDetailSerializer,
        operation_id="purchase_orders_get",
        tags=["purchasing"],
    )
    def get(self, request: Request, order_id: UUID) -> Response:
        return _order_response(request, order_id)

    @extend_schema(
        request=s.PurchaseOrderInputSerializer,
        responses=s.PurchaseOrderDetailSerializer,
        operation_id="purchase_orders_update",
        tags=["purchasing"],
    )
    def patch(self, request: Request, order_id: UUID) -> Response:
        data = s.PurchaseOrderInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        orders.update_order(order_id, _order_input(data.validated_data), by=_user(request))
        return _order_response(request, order_id)

    @extend_schema(
        request=None,
        responses={204: None},
        operation_id="purchase_orders_delete",
        tags=["purchasing"],
    )
    def delete(self, request: Request, order_id: UUID) -> Response:
        orders.delete_order(order_id, by=_user(request))
        return Response(status=204)


class PurchaseOrderSendView(PurchasingView):
    """Send to the supplier: its copy by email (when it has an address) and a link to share."""

    required_permissions = {"POST": MANAGE}

    @extend_schema(
        request=None,
        responses=s.SendResultSerializer,
        parameters=[IDEMPOTENCY],
        operation_id="purchase_orders_send",
        tags=["purchasing"],
    )
    @idempotent("purchasing.orders.send")
    def post(self, request: Request, order_id: UUID) -> Response:
        sent = orders.send_order(order_id, by=_user(request))
        detail = _order_response(request, order_id).data
        return Response({"order": detail, "share_link": sent.share_link, "emailed": sent.emailed})


class PurchaseOrderCancelView(PurchasingView):
    required_permissions = {"POST": MANAGE}

    @extend_schema(
        request=s.PurchaseOrderReasonSerializer,
        responses=s.PurchaseOrderDetailSerializer,
        operation_id="purchase_orders_cancel",
        tags=["purchasing"],
    )
    def post(self, request: Request, order_id: UUID) -> Response:
        data = s.PurchaseOrderReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        orders.cancel_order(order_id, reason=data.validated_data["reason"], by=_user(request))
        return _order_response(request, order_id)


class PurchaseOrderCloseView(PurchasingView):
    required_permissions = {"POST": MANAGE}

    @extend_schema(
        request=s.PurchaseOrderReasonSerializer,
        responses=s.PurchaseOrderDetailSerializer,
        operation_id="purchase_orders_close",
        tags=["purchasing"],
    )
    def post(self, request: Request, order_id: UUID) -> Response:
        data = s.PurchaseOrderReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        orders.close_order(order_id, reason=data.validated_data["reason"], by=_user(request))
        return _order_response(request, order_id)


class PurchaseOrderPdfView(PurchasingView):
    """A short link to the PDF: the supplier's copy with costs for staff who can see costs, else
    the copy without prices; 202 while it is being printed."""

    @extend_schema(
        responses={200: DocumentLinkSerializer, 202: DocumentLinkSerializer},
        operation_id="purchase_orders_pdf",
        tags=["purchasing"],
    )
    def get(self, request: Request, order_id: UUID) -> Response:
        from apps.billing.documents import link

        order = PurchaseOrder.objects.filter(pk=order_id).first()
        if order is None:
            raise NotFound()
        key = order.pdf_key if _costs(request) else order.plain_pdf_key
        body, status = link(key, order.pdf_status)
        return Response(body, status=status)


class PurchaseOrderReceiveView(PurchasingView):
    """A goods-receipt draft with what is still due and the order's costs (the open draft, if one
    is being entered already)."""

    required_permissions = {"POST": "stock.inward"}

    @extend_schema(
        request=None,
        responses={201: ReceiptDetailSerializer},
        operation_id="purchase_orders_receive",
        tags=["purchasing"],
    )
    def post(self, request: Request, order_id: UUID) -> Response:
        from apps.inventory import selectors as stock_selectors

        inward = receiving.receive_order(order_id, by=_user(request))
        found = stock_selectors.receipt(inward.pk)
        context = {"request": request, "show_cost": _costs(request)}
        return Response(ReceiptDetailSerializer(found, context=context).data, status=201)


class ProductOnOrderView(PurchasingView):
    """How much of a product is on order and when it is expected: for anyone who sees orders or
    stock (sales staff too), without suppliers or prices."""

    required_permissions: dict[str, Requirement] = {"GET": AnyOf(("orders.view", "stock.view"))}

    @extend_schema(
        responses=s.OnOrderSerializer, operation_id="product_on_order", tags=["purchasing"]
    )
    def get(self, request: Request, product_id: UUID) -> Response:
        if not selectors.product_exists(product_id):
            raise NotFound()
        found = selectors.on_order([product_id]).get(product_id)
        body = {
            "quantity": found.quantity if found else Decimal("0"),
            "expected_date": found.expected_date if found else None,
            "late": found.late if found else False,
            "orders": selectors.on_order_detail(product_id),
        }
        return Response(s.OnOrderSerializer(body).data)
