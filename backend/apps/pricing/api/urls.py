from django.urls import path

from apps.pricing.api import tools as t
from apps.pricing.api import views as v

urlpatterns = [
    path("price-lists/", v.PriceListListCreateView.as_view(), name="price-lists"),
    path(
        "price-lists/<uuid:price_list_id>/",
        v.PriceListDetailView.as_view(),
        name="price-list-detail",
    ),
    path(
        "price-lists/<uuid:price_list_id>/items/",
        v.PriceListItemsView.as_view(),
        name="price-list-items",
    ),
    path(
        "price-lists/<uuid:price_list_id>/items/<uuid:product_id>/",
        v.PriceListItemDetailView.as_view(),
        name="price-list-item-detail",
    ),
    path("retailer-prices/", v.RetailerPriceListCreateView.as_view(), name="retailer-prices"),
    path(
        "retailer-prices/<uuid:price_id>/",
        v.RetailerPriceDetailView.as_view(),
        name="retailer-price-detail",
    ),
    path("discount-rules/", v.DiscountRuleListCreateView.as_view(), name="discount-rules"),
    path("pricing/preview/", v.PricePreviewView.as_view(), name="pricing-preview"),
    path(
        "retailers/<uuid:retailer_id>/prices/",
        v.RetailerPriceSheetView.as_view(),
        name="retailer-price-sheet",
    ),
    path(
        "discount-rules/<uuid:rule_id>/",
        v.DiscountRuleDetailView.as_view(),
        name="discount-rule-detail",
    ),
    path(
        "retailers/<uuid:retailer_id>/discount-grid/",
        t.DiscountGridView.as_view(),
        name="retailer-discount-grid",
    ),
    path(
        "retailers/<uuid:retailer_id>/discount-grid/preview/",
        t.DiscountGridPreviewView.as_view(),
        name="retailer-discount-grid-preview",
    ),
    path(
        "retailers/<uuid:retailer_id>/copy-pricing/preview/",
        t.CopyPricingPreviewView.as_view(),
        name="retailer-copy-pricing-preview",
    ),
    path(
        "retailers/<uuid:retailer_id>/copy-pricing/",
        t.CopyPricingView.as_view(),
        name="retailer-copy-pricing",
    ),
    path(
        "retailers/<uuid:retailer_id>/free-products/",
        t.FreeProductsView.as_view(),
        name="retailer-free-products",
    ),
    path(
        "price-lists/<uuid:price_list_id>/adjust/preview/",
        t.PriceListAdjustPreviewView.as_view(),
        name="price-list-adjust-preview",
    ),
    path(
        "price-lists/<uuid:price_list_id>/adjust/",
        t.PriceListAdjustView.as_view(),
        name="price-list-adjust",
    ),
    path("pricing/shop-report/", t.ShopPricingReportView.as_view(), name="pricing-shop-report"),
    path(
        "pricing/shop-report/export/",
        t.ShopPricingReportExportView.as_view(),
        name="pricing-shop-report-export",
    ),
]
