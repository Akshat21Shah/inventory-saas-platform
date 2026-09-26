from django.urls import path

from apps.inventory.api import views as v

urlpatterns = [
    path("warehouses/", v.WarehouseListView.as_view(), name="warehouses"),
    path(
        "warehouses/<uuid:warehouse_id>/",
        v.WarehouseDetailView.as_view(),
        name="warehouse-detail",
    ),
    path("stock/", v.StockListView.as_view(), name="stock"),
    path("stock/summary/", v.StockSummaryView.as_view(), name="stock-summary"),
    path("stock/lookup/", v.LookupView.as_view(), name="stock-lookup"),
    path("stock/movements/", v.MovementListView.as_view(), name="stock-movements"),
    path("stock/alerts/", v.AlertListView.as_view(), name="stock-alerts"),
    path("stock/inwards/", v.ReceiptListCreateView.as_view(), name="stock-inwards"),
    path(
        "stock/inwards/<uuid:inward_id>/",
        v.ReceiptDetailView.as_view(),
        name="stock-inward-detail",
    ),
    path(
        "stock/inwards/<uuid:inward_id>/post/",
        v.ReceiptPostView.as_view(),
        name="stock-inward-post",
    ),
    path(
        "stock/inwards/<uuid:inward_id>/complete-costs/",
        v.CompleteCostsView.as_view(),
        name="stock-inward-complete-costs",
    ),
    path("stock/adjustments/", v.AdjustmentListCreateView.as_view(), name="stock-adjustments"),
    path(
        "stock/adjustments/<uuid:adjustment_id>/",
        v.AdjustmentDetailView.as_view(),
        name="stock-adjustment-detail",
    ),
    path("stock/<uuid:product_id>/", v.StockDetailView.as_view(), name="stock-detail"),
    path(
        "stock/<uuid:product_id>/reorder-level/",
        v.ReorderLevelView.as_view(),
        name="stock-reorder-level",
    ),
    path("reports/stock/low-stock/", v.LowStockView.as_view(), name="report-low-stock"),
    path(
        "reports/stock/low-stock/export/",
        v.LowStockExportView.as_view(),
        name="report-low-stock-export",
    ),
    path("reports/stock/valuation/", v.ValuationView.as_view(), name="report-valuation"),
    path(
        "reports/stock/valuation/products/",
        v.ValuationProductsView.as_view(),
        name="report-valuation-products",
    ),
    path(
        "reports/stock/valuation/export/",
        v.ValuationExportView.as_view(),
        name="report-valuation-export",
    ),
]
