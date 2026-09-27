from django.urls import path

from apps.shop.api import cart as c
from apps.shop.api import orders as o
from apps.shop.api import views as v

urlpatterns = [
    path("categories/", v.ShopCategoriesView.as_view(), name="shop-categories"),
    path("brands/", v.ShopBrandsView.as_view(), name="shop-brands"),
    path("products/", v.ShopProductsView.as_view(), name="shop-products"),
    path("products/<uuid:product_id>/", v.ShopProductDetailView.as_view(), name="shop-product"),
    path("cart/", c.ShopCartView.as_view(), name="shop-cart"),
    path("cart/lines/<uuid:product_id>/", c.ShopCartLineView.as_view(), name="shop-cart-line"),
    path(
        "cart/reduce-to-available/",
        c.ShopCartReduceView.as_view(),
        name="shop-cart-reduce",
    ),
    path("addresses/", c.ShopAddressesView.as_view(), name="shop-addresses"),
    path("orders/", o.ShopOrdersView.as_view(), name="shop-orders"),
]
