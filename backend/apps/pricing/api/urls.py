from django.urls import path

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
    path(
        "discount-rules/<uuid:rule_id>/",
        v.DiscountRuleDetailView.as_view(),
        name="discount-rule-detail",
    ),
]
