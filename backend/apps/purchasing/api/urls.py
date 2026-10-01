from django.urls import path

from apps.purchasing.api import views as v

urlpatterns = [
    path("suppliers/", v.SupplierListCreateView.as_view(), name="suppliers"),
    path(
        "suppliers/from-receipts/",
        v.ReceiptSuppliersView.as_view(),
        name="suppliers-from-receipts",
    ),
    path("suppliers/<uuid:supplier_id>/", v.SupplierDetailView.as_view(), name="supplier"),
    path(
        "suppliers/<uuid:supplier_id>/products/",
        v.SupplierProductsView.as_view(),
        name="supplier-products",
    ),
    path(
        "products/<uuid:product_id>/suppliers/",
        v.ProductSuppliersView.as_view(),
        name="product-suppliers",
    ),
]
