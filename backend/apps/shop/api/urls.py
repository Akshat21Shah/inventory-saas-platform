from django.urls import path

from apps.shop.api import views as v

urlpatterns = [
    path("categories/", v.ShopCategoriesView.as_view(), name="shop-categories"),
    path("brands/", v.ShopBrandsView.as_view(), name="shop-brands"),
    path("products/", v.ShopProductsView.as_view(), name="shop-products"),
    path("products/<uuid:product_id>/", v.ShopProductDetailView.as_view(), name="shop-product"),
]
