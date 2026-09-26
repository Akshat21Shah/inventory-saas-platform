from django.urls import path
from drf_spectacular.utils import extend_schema, extend_schema_view

from apps.dataio.api import views as v

ProductExport = extend_schema_view(get=extend_schema(operation_id="products_export"))(
    v.ProductExportView
)

RetailerExport = extend_schema_view(get=extend_schema(operation_id="retailers_export"))(
    v.RetailerExportView
)

SpecialPriceExport = extend_schema_view(get=extend_schema(operation_id="special_prices_export"))(
    v.SpecialPriceExportView
)
PriceListItemExport = extend_schema_view(get=extend_schema(operation_id="price_list_items_export"))(
    v.PriceListItemExportView
)
DiscountRuleExport = extend_schema_view(get=extend_schema(operation_id="discount_rules_export"))(
    v.DiscountRuleExportView
)
StockCountExport = extend_schema_view(get=extend_schema(operation_id="stock_count_export"))(
    v.StockCountExportView
)

urlpatterns = [
    path("imports/", v.ImportListCreateView.as_view(), name="imports"),
    path("imports/templates/<str:kind>/", v.ImportTemplateView.as_view(), name="import-template"),
    path("imports/<uuid:job_id>/", v.ImportDetailView.as_view(), name="import-detail"),
    path("imports/<uuid:job_id>/commit/", v.ImportCommitView.as_view(), name="import-commit"),
    path("imports/<uuid:job_id>/report/", v.ImportReportView.as_view(), name="import-report"),
    path("products/export/", ProductExport.as_view(), name="products-export"),
    path("retailers/export/", RetailerExport.as_view(), name="retailers-export"),
    path("retailer-prices/export/", SpecialPriceExport.as_view(), name="special-prices-export"),
    path(
        "price-lists/items/export/",
        PriceListItemExport.as_view(),
        name="price-list-items-export",
    ),
    path("discount-rules/export/", DiscountRuleExport.as_view(), name="discount-rules-export"),
    path("stock/export/", StockCountExport.as_view(), name="stock-count-export"),
]
