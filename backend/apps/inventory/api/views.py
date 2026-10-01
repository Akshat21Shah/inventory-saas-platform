"""Inventory API (PLAN §3.7, ADR-041). Thin: permission → serializer → service/selector."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.dataio import services as dataio
from apps.inventory import adjustments, receipts, selectors, services
from apps.inventory.api import serializers as s
from apps.inventory.models import (
    MovementType,
    ReferenceType,
    StockAdjustment,
    StockAlert,
    StockInward,
    StockMovement,
    Warehouse,
)
from common.errors import InvalidFields, NotFound
from common.idempotency import idempotent
from common.permissions import AllOf, AnyOf, HasPermission

VIEW, INWARD, ADJUST = "stock.view", "stock.inward", "stock.adjust"
REPORTS = "reports.stock"
COSTS = "costs.view"  # ADR-042
READ_RECEIPTS = AnyOf((INWARD, COSTS))  # costs.view users open "Goods receipts awaiting cost"
# Stock value: costs.view with the stock or the financial reports (ADR-042; Accounts included).
VALUATION = AllOf((COSTS, AnyOf((REPORTS, "reports.financial"))))


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


def _context(request: Request) -> dict[str, Any]:
    return {"request": request, "show_cost": _user(request).has_permission_code(COSTS)}


def _fake(view: Any, model: Any) -> QuerySet[Any] | None:
    return model.objects.unscoped().none() if getattr(view, "swagger_fake_view", False) else None


class Paged(CursorPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class ByName(Paged):
    ordering = ("name", "id")


class Newest(Paged):
    ordering = ("-created_at", "-id")


class NewestAlert(Paged):
    ordering = ("-opened_at", "-id")


def _uuid(value: str | None, field: str) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise InvalidFields({field: ["Not a valid id."]}) from exc


def _date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidFields({field: ["Use YYYY-MM-DD."]}) from exc


class Guarded(APIView):
    permission_classes = [HasPermission]


# --- Warehouses --------------------------------------------------------------------------------


class WarehouseListView(Guarded, generics.ListAPIView[Warehouse]):
    required_permission = VIEW
    serializer_class = s.WarehouseSerializer
    pagination_class = None

    def get_queryset(self) -> QuerySet[Warehouse]:
        fake = _fake(self, Warehouse)
        return fake if fake is not None else selectors.warehouses()

    @extend_schema(operation_id="warehouses_list", tags=["inventory"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class WarehouseDetailView(Guarded):
    required_permissions = {"GET": VIEW, "PATCH": "settings.manage"}

    def _get(self, warehouse_id: UUID) -> Warehouse:
        found = selectors.warehouses().filter(pk=warehouse_id).first()
        if found is None:
            raise NotFound()
        return found

    @extend_schema(
        operation_id="warehouses_retrieve", tags=["inventory"], responses=s.WarehouseSerializer
    )
    def get(self, request: Request, warehouse_id: UUID) -> Response:
        return Response(s.WarehouseSerializer(self._get(warehouse_id)).data)

    @extend_schema(
        operation_id="warehouses_update",
        tags=["inventory"],
        request=s.WarehouseSerializer,
        responses=s.WarehouseSerializer,
    )
    def patch(self, request: Request, warehouse_id: UUID) -> Response:
        data = s.WarehouseSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        changes = dict(data.validated_data)
        if "state" in changes:
            state = changes.pop("state")
            changes["state_id"] = state.pk if state else None
        warehouse = services.update_warehouse(warehouse_id, changes, by=_user(request))
        return Response(s.WarehouseSerializer(warehouse).data)


# --- Stock -------------------------------------------------------------------------------------

STOCK_FILTERS = [
    OpenApiParameter("search", str),
    OpenApiParameter("category", UUID),
    OpenApiParameter("brand", UUID),
    OpenApiParameter("status", str, enum=["IN_STOCK", "LOW", "OUT", "BACKORDERED"]),
    OpenApiParameter("is_active", bool),
    OpenApiParameter("no_reorder_level", bool),
]


class StockListView(Guarded, generics.ListAPIView[Any]):
    required_permission = VIEW
    serializer_class = s.StockRowSerializer
    pagination_class = ByName

    def get_queryset(self) -> QuerySet[Any]:
        from apps.catalog.models import Product

        if getattr(self, "swagger_fake_view", False):
            return Product.objects.unscoped().none()
        q = self.request.query_params
        active = q.get("is_active")
        return selectors.stock_list(
            selectors.StockFilters(
                search=q.get("search", ""),
                category_id=_uuid(q.get("category"), "category"),
                brand_id=_uuid(q.get("brand"), "brand"),
                status=q.get("status", ""),
                is_active=None if active in (None, "") else active == "true",
                no_reorder_level=q.get("no_reorder_level") == "true",
            )
        )

    @extend_schema(operation_id="stock_list", tags=["inventory"], parameters=STOCK_FILTERS)
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class StockSummaryView(Guarded):
    required_permission = VIEW

    @extend_schema(operation_id="stock_summary", tags=["inventory"], responses=s.SummarySerializer)
    def get(self, request: Request) -> Response:
        sees_costs = _user(request).has_permission_code(COSTS)
        return Response(
            {
                "alerts": selectors.alert_counts(),
                "receipts_awaiting_cost": (
                    selectors.receipts_awaiting_cost_count() if sees_costs else None
                ),
            }
        )


class StockDetailView(Guarded):
    required_permission = VIEW

    @extend_schema(
        operation_id="stock_retrieve", tags=["inventory"], responses=s.StockDetailSerializer
    )
    def get(self, request: Request, product_id: UUID) -> Response:
        product = selectors.stock_product(product_id)
        if product is None:
            raise NotFound()
        return Response(s.StockDetailSerializer(product, context=_context(request)).data)


class ReorderLevelView(Guarded):
    required_permission = AnyOf(("products.manage", ADJUST))

    @extend_schema(
        operation_id="stock_reorder_level_update",
        tags=["inventory"],
        request=s.ReorderLevelSerializer,
        responses=s.StockDetailSerializer,
    )
    def patch(self, request: Request, product_id: UUID) -> Response:
        data = s.ReorderLevelSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        adjustments.set_reorder_level(
            product_id, data.validated_data["reorder_level"], by=_user(request)
        )
        product = selectors.stock_product(product_id)
        return Response(s.StockDetailSerializer(product, context=_context(request)).data)


class LookupView(Guarded):
    required_permission = AnyOf((INWARD, ADJUST))

    @extend_schema(
        operation_id="stock_lookup",
        tags=["inventory"],
        parameters=[OpenApiParameter("code", str, required=True)],
        responses={200: s.LookupSerializer, 404: OpenApiResponse(description="No such product")},
    )
    def get(self, request: Request) -> Response:
        product = selectors.lookup(request.query_params.get("code", ""))
        if product is None:
            raise NotFound("No product has this barcode or code.")
        return Response(s.LookupSerializer(product).data)


class MovementListView(Guarded, generics.ListAPIView[StockMovement]):
    required_permission = VIEW
    serializer_class = s.MovementSerializer
    pagination_class = Newest

    def get_queryset(self) -> QuerySet[StockMovement]:
        fake = _fake(self, StockMovement)
        if fake is not None:
            return fake
        q = self.request.query_params
        return selectors.movements(
            selectors.MovementFilters(
                product_id=_uuid(q.get("product"), "product"),
                movement_type=q.get("type", ""),
                reference_type=q.get("reference_type", ""),
                reference_id=_uuid(q.get("reference"), "reference"),
                date_from=_date(q.get("from"), "from"),
                date_to=_date(q.get("to"), "to"),
            )
        )

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), **_context(self.request)}

    @extend_schema(
        operation_id="stock_movements_list",
        tags=["inventory"],
        parameters=[
            OpenApiParameter("product", UUID),
            OpenApiParameter("type", str, enum=MovementType.values),
            OpenApiParameter("reference_type", str, enum=ReferenceType.values),
            OpenApiParameter("reference", UUID),
            OpenApiParameter("from", date),
            OpenApiParameter("to", date),
        ],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class AlertListView(Guarded, generics.ListAPIView[StockAlert]):
    required_permission = VIEW
    serializer_class = s.AlertSerializer
    pagination_class = NewestAlert

    def get_queryset(self) -> QuerySet[StockAlert]:
        fake = _fake(self, StockAlert)
        if fake is not None:
            return fake
        q = self.request.query_params
        return selectors.alerts(status=q.get("status", "OPEN"), alert_type=q.get("type", ""))

    @extend_schema(
        operation_id="stock_alerts_list",
        tags=["inventory"],
        parameters=[
            OpenApiParameter("status", str, enum=["OPEN", "RESOLVED", ""]),
            OpenApiParameter("type", str, enum=StockAlert.Type.values),
        ],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


# --- Goods receipts ----------------------------------------------------------------------------


def _receipt_input(data: dict[str, Any]) -> receipts.ReceiptInput:
    return receipts.ReceiptInput(
        supplier_name=data.get("supplier_name", ""),
        supplier_id=data.get("supplier_id"),
        supplier_ref=data.get("supplier_ref", ""),
        bill_number=data.get("bill_number", ""),
        bill_date=data.get("bill_date"),
        notes=data.get("notes", ""),
        lines=[
            receipts.LineInput(
                product_id=line["product_id"],
                entered_qty=line["entered_qty"],
                entered_unit=line.get("entered_unit", "BASE"),
                entered_cost=line.get("entered_cost"),
                id=line.get("id"),
            )
            for line in data["lines"]
        ],
    )


def _receipt_response(request: Request, inward_id: UUID, status: int = 200) -> Response:
    found = selectors.receipt(inward_id)
    if found is None:
        raise NotFound()
    return Response(s.ReceiptDetailSerializer(found, context=_context(request)).data, status=status)


class ReceiptListCreateView(Guarded, generics.ListAPIView[StockInward]):
    required_permissions = {"GET": READ_RECEIPTS, "POST": INWARD}
    serializer_class = s.ReceiptSerializer
    pagination_class = Newest

    def get_queryset(self) -> QuerySet[StockInward]:
        fake = _fake(self, StockInward)
        if fake is not None:
            return fake
        q = self.request.query_params
        return selectors.receipts(
            status=q.get("status", ""), awaiting_cost=q.get("awaiting_cost") == "true"
        )

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), **_context(self.request)}

    @extend_schema(
        operation_id="stock_receipts_list",
        tags=["inventory"],
        parameters=[
            OpenApiParameter("status", str, enum=StockInward.Status.values),
            OpenApiParameter("awaiting_cost", bool),
        ],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="stock_receipts_create",
        tags=["inventory"],
        request=s.ReceiptCreateSerializer,
        responses={201: s.ReceiptDetailSerializer},
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, True)],
    )
    @idempotent("stock.receipts.create")
    def post(self, request: Request) -> Response:
        data = s.ReceiptCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        payload = _receipt_input(data.validated_data)
        by = _user(request)
        if data.validated_data["post"]:
            inward = receipts.create_and_post(payload, by=by)
        else:
            inward = receipts.create_draft(payload, by=by)
        return _receipt_response(request, inward.pk, status=201)


class ReceiptDetailView(Guarded):
    required_permissions = {"GET": READ_RECEIPTS, "PATCH": INWARD, "DELETE": INWARD}

    @extend_schema(
        operation_id="stock_receipts_retrieve",
        tags=["inventory"],
        responses=s.ReceiptDetailSerializer,
    )
    def get(self, request: Request, inward_id: UUID) -> Response:
        return _receipt_response(request, inward_id)

    @extend_schema(
        operation_id="stock_receipts_update",
        tags=["inventory"],
        request=s.ReceiptInputSerializer,
        responses=s.ReceiptDetailSerializer,
    )
    def patch(self, request: Request, inward_id: UUID) -> Response:
        data = s.ReceiptInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        receipts.update_draft(inward_id, _receipt_input(data.validated_data), by=_user(request))
        return _receipt_response(request, inward_id)

    @extend_schema(operation_id="stock_receipts_destroy", tags=["inventory"], responses={204: None})
    def delete(self, request: Request, inward_id: UUID) -> Response:
        receipts.delete_draft(inward_id, by=_user(request))
        return Response(status=204)


class ReceiptPostView(Guarded):
    required_permission = INWARD

    @extend_schema(
        operation_id="stock_receipts_post",
        tags=["inventory"],
        request=None,
        responses=s.ReceiptDetailSerializer,
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, True)],
    )
    @idempotent("stock.receipts.post")
    def post(self, request: Request, inward_id: UUID) -> Response:
        receipts.post(inward_id, by=_user(request))
        return _receipt_response(request, inward_id)


class CompleteCostsView(Guarded):
    required_permission = "costs.manage"

    @extend_schema(
        operation_id="stock_receipts_complete_costs",
        tags=["inventory"],
        request=s.CompleteCostsSerializer,
        responses=s.ReceiptDetailSerializer,
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, True)],
    )
    @idempotent("stock.receipts.complete_costs")
    def post(self, request: Request, inward_id: UUID) -> Response:
        data = s.CompleteCostsSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        costs: dict[UUID, Decimal] = {}
        for row in data.validated_data["costs"]:
            if row["line_id"] in costs:
                raise InvalidFields({"costs": ["Each line can have one cost."]})
            costs[row["line_id"]] = row["entered_cost"]
        receipts.complete_costs(inward_id, costs, by=_user(request))
        return _receipt_response(request, inward_id)


# --- Adjustments -------------------------------------------------------------------------------


class AdjustmentListCreateView(Guarded, generics.ListAPIView[StockAdjustment]):
    required_permission = ADJUST
    serializer_class = s.AdjustmentSerializer
    pagination_class = Newest

    def get_queryset(self) -> QuerySet[StockAdjustment]:
        fake = _fake(self, StockAdjustment)
        return fake if fake is not None else selectors.adjustments()

    @extend_schema(operation_id="stock_adjustments_list", tags=["inventory"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="stock_adjustments_create",
        tags=["inventory"],
        request=s.AdjustmentInputSerializer,
        responses={201: s.AdjustmentDetailSerializer},
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, True)],
    )
    @idempotent("stock.adjustments.create")
    def post(self, request: Request) -> Response:
        data = s.AdjustmentInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        result = adjustments.create_adjustment(
            adjustments.AdjustmentInput(
                reason_code=v["reason_code"],
                note=v["note"],
                lines=[
                    adjustments.AdjustmentLineInput(
                        line["product_id"], line["mode"], line["quantity"]
                    )
                    for line in v["lines"]
                ],
            ),
            by=_user(request),
        )
        found = selectors.adjustment(result.adjustment.pk)
        body = dict(s.AdjustmentDetailSerializer(found).data)
        body["unchanged"] = result.unchanged
        return Response(body, status=201)


class AdjustmentDetailView(Guarded):
    required_permission = ADJUST

    @extend_schema(
        operation_id="stock_adjustments_retrieve",
        tags=["inventory"],
        responses=s.AdjustmentDetailSerializer,
    )
    def get(self, request: Request, adjustment_id: UUID) -> Response:
        found = selectors.adjustment(adjustment_id)
        if found is None:
            raise NotFound()
        return Response(s.AdjustmentDetailSerializer(found).data)


# --- Reports -----------------------------------------------------------------------------------

REPORT_FILTERS = [OpenApiParameter("category", UUID), OpenApiParameter("brand", UUID)]


def _report_filters(request: Request) -> selectors.ReportFilters:
    q = request.query_params
    return selectors.ReportFilters(
        category_id=_uuid(q.get("category"), "category"), brand_id=_uuid(q.get("brand"), "brand")
    )


def _xlsx(rows: list[list[Any]], widths: list[int], filename: str) -> HttpResponse:
    response = HttpResponse(dataio.spreadsheet(rows, widths), content_type=dataio.XLSX)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


class LowStockView(Guarded, generics.ListAPIView[Any]):
    required_permission = REPORTS
    serializer_class = s.LowStockRowSerializer
    pagination_class = ByName

    def get_queryset(self) -> QuerySet[Any]:
        from apps.catalog.models import Product

        if getattr(self, "swagger_fake_view", False):
            return Product.objects.unscoped().none()
        return selectors.low_stock(_report_filters(self.request))

    @extend_schema(operation_id="reports_low_stock", tags=["reports"], parameters=REPORT_FILTERS)
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class LowStockSummaryView(Guarded):
    required_permission = REPORTS

    @extend_schema(
        operation_id="reports_low_stock_summary",
        tags=["reports"],
        parameters=REPORT_FILTERS,
        responses=s.LowStockSummarySerializer,
    )
    def get(self, request: Request) -> Response:
        filters = _report_filters(request)
        return Response(
            {
                "low_stock": selectors.low_stock(filters).count(),
                "without_reorder_level": selectors.products_without_reorder_level(filters),
            }
        )


class LowStockExportView(Guarded):
    required_permission = REPORTS

    @extend_schema(
        operation_id="reports_low_stock_export",
        tags=["reports"],
        parameters=REPORT_FILTERS,
        responses={(200, "application/octet-stream"): bytes},
    )
    def get(self, request: Request) -> HttpResponse:
        rows: list[list[Any]] = [
            [
                "Code",
                "Product",
                "Category",
                "Brand",
                "Unit",
                "Available",
                "Reorder level",
                "Short by",
            ]
        ]
        for p in selectors.low_stock(_report_filters(request)).order_by("name", "id"):
            rows.append(
                [
                    p.code,
                    p.name,
                    p.category.name if p.category else "",
                    p.brand.name if p.brand else "",
                    p.unit.code,
                    p.available,  # type: ignore[attr-defined]
                    p.reorder_level,
                    p.shortfall,  # type: ignore[attr-defined]
                ]
            )
        return _xlsx(rows, [16, 36, 20, 18, 8, 12, 14, 12], "low-stock.xlsx")


class ValuationView(Guarded):
    required_permission = VALUATION

    @extend_schema(
        operation_id="reports_stock_valuation",
        tags=["reports"],
        parameters=REPORT_FILTERS,
        responses=s.ValuationSerializer,
    )
    def get(self, request: Request) -> Response:
        return Response(s.ValuationSerializer(selectors.valuation(_report_filters(request))).data)


class ValuationProductsView(Guarded, generics.ListAPIView[Any]):
    required_permission = VALUATION
    serializer_class = s.ValuationRowSerializer
    pagination_class = ByName

    def get_queryset(self) -> QuerySet[Any]:
        from apps.catalog.models import Product

        if getattr(self, "swagger_fake_view", False):
            return Product.objects.unscoped().none()
        missing = self.request.query_params.get("missing_cost")
        return selectors.valuation_products(
            _report_filters(self.request),
            missing_cost=None if missing in (None, "") else missing == "true",
        )

    @extend_schema(
        operation_id="reports_stock_valuation_products",
        tags=["reports"],
        parameters=[*REPORT_FILTERS, OpenApiParameter("missing_cost", bool)],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class ValuationExportView(Guarded):
    required_permission = VALUATION

    @extend_schema(
        operation_id="reports_stock_valuation_export",
        tags=["reports"],
        parameters=REPORT_FILTERS,
        responses={(200, "application/octet-stream"): bytes},
    )
    def get(self, request: Request) -> HttpResponse:
        filters = _report_filters(request)
        paths = selectors.category_paths()
        rows: list[list[Any]] = [
            [
                "Code",
                "Product",
                "Category",
                "Brand",
                "Unit",
                "On hand",
                "Cost price (before GST)",
                "Value",
                "Note",
            ]
        ]
        for p in selectors.valuation_products(filters).order_by("name", "id"):
            value = selectors.product_value(p)
            rows.append(
                [
                    p.code,
                    p.name,
                    paths.get(p.category_id, "") if p.category_id else "",
                    p.brand.name if p.brand else "",
                    p.unit.code,
                    p.on_hand,  # type: ignore[attr-defined]
                    p.cost_price,
                    value,
                    "" if value is not None else "No cost price: not in the total",
                ]
            )
        totals = selectors.valuation(filters)
        rows.append([])
        rows.append(["", "Total value", "", "", "", "", "", totals.total_value, ""])
        rows.append(
            ["", "Products without a cost price", "", "", "", "", "", "", totals.missing_cost]
        )
        for title, buckets in (("By category", totals.by_category), ("By brand", totals.by_brand)):
            rows.append([])
            rows.append(["", title, "", "", "", "Products", "", "Value", "Without a cost price"])
            for bucket in buckets:
                name = bucket.name or "(none)"
                row = ["", name, "", "", "", bucket.products, "", bucket.value, bucket.missing_cost]
                rows.append(row)
        return _xlsx(rows, [16, 36, 24, 18, 8, 12, 20, 14, 32], "stock-valuation.xlsx")
