from django.urls import path

from apps.catalog.api import views as v

urlpatterns = [
    path("categories/", v.CategoryListCreateView.as_view(), name="catalog-categories"),
    path("categories/tree/", v.CategoryTreeView.as_view(), name="catalog-category-tree"),
    path(
        "categories/<uuid:category_id>/",
        v.CategoryDetailView.as_view(),
        name="catalog-category-detail",
    ),
    path("brands/", v.BrandListCreateView.as_view(), name="catalog-brands"),
    path("brands/<uuid:brand_id>/", v.BrandDetailView.as_view(), name="catalog-brand-detail"),
    path("units/", v.UnitListCreateView.as_view(), name="catalog-units"),
    path("units/<uuid:unit_id>/", v.UnitDetailView.as_view(), name="catalog-unit-detail"),
    path("products/", v.ProductListCreateView.as_view(), name="catalog-products"),
    path("products/lookup/", v.ProductLookupView.as_view(), name="catalog-product-lookup"),
    path("products/search/", v.ProductSearchView.as_view(), name="catalog-product-search"),
    path("products/bulk/", v.ProductBulkView.as_view(), name="catalog-products-bulk"),
    path("products/hsn-hint/", v.HsnHintView.as_view(), name="catalog-hsn-hint"),
    path("products/tax-options/", v.TaxOptionsView.as_view(), name="catalog-tax-options"),
    path(
        "products/tax-rates/schedule/",
        v.TaxRateScheduleView.as_view(),
        name="catalog-tax-rate-schedule",
    ),
    path(
        "products/<uuid:product_id>/", v.ProductDetailView.as_view(), name="catalog-product-detail"
    ),
    path(
        "products/<uuid:product_id>/barcodes/",
        v.ProductBarcodesView.as_view(),
        name="catalog-product-barcodes",
    ),
    path(
        "products/<uuid:product_id>/barcodes/<uuid:barcode_id>/",
        v.ProductBarcodeDetailView.as_view(),
        name="catalog-product-barcode-detail",
    ),
    path(
        "products/<uuid:product_id>/images/",
        v.ProductImagesView.as_view(),
        name="catalog-product-images",
    ),
    path(
        "products/<uuid:product_id>/images/<uuid:image_id>/",
        v.ProductImageDetailView.as_view(),
        name="catalog-product-image-detail",
    ),
    path(
        "products/<uuid:product_id>/tax-rates/",
        v.ProductTaxRatesView.as_view(),
        name="catalog-product-tax-rates",
    ),
    path(
        "products/<uuid:product_id>/tax-rates/<uuid:rate_id>/cancel/",
        v.ProductTaxRateCancelView.as_view(),
        name="catalog-product-tax-rate-cancel",
    ),
]
