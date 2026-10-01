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
    path("purchase-orders/", v.PurchaseOrderListCreateView.as_view(), name="purchase-orders"),
    path(
        "purchase-orders/<uuid:order_id>/",
        v.PurchaseOrderDetailView.as_view(),
        name="purchase-order",
    ),
    path(
        "purchase-orders/<uuid:order_id>/send/",
        v.PurchaseOrderSendView.as_view(),
        name="purchase-order-send",
    ),
    path(
        "purchase-orders/<uuid:order_id>/cancel/",
        v.PurchaseOrderCancelView.as_view(),
        name="purchase-order-cancel",
    ),
    path(
        "purchase-orders/<uuid:order_id>/close/",
        v.PurchaseOrderCloseView.as_view(),
        name="purchase-order-close",
    ),
    path(
        "purchase-orders/<uuid:order_id>/receive/",
        v.PurchaseOrderReceiveView.as_view(),
        name="purchase-order-receive",
    ),
    path(
        "products/<uuid:product_id>/on-order/",
        v.ProductOnOrderView.as_view(),
        name="product-on-order",
    ),
    path(
        "purchase-orders/<uuid:order_id>/pdf/",
        v.PurchaseOrderPdfView.as_view(),
        name="purchase-order-pdf",
    ),
    path(
        "products/<uuid:product_id>/suppliers/",
        v.ProductSuppliersView.as_view(),
        name="product-suppliers",
    ),
]
