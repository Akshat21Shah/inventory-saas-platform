from django.urls import path

from apps.shop.api import billing as b
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
    path("home/", o.ShopHomeView.as_view(), name="shop-home"),
    path("orders/", o.ShopOrdersView.as_view(), name="shop-orders"),
    path("orders/<uuid:order_id>/", o.ShopOrderDetailView.as_view(), name="shop-order"),
    path(
        "orders/<uuid:order_id>/cancel/", o.ShopOrderCancelView.as_view(), name="shop-order-cancel"
    ),
    path(
        "orders/<uuid:order_id>/repeat/", o.ShopOrderRepeatView.as_view(), name="shop-order-repeat"
    ),
    path(
        "order-lines/<uuid:line_id>/cancel-backorder/",
        o.ShopCancelBackorderView.as_view(),
        name="shop-order-line-cancel-backorder",
    ),
    path(
        "fulfilments/<uuid:fulfilment_id>/received/",
        o.ShopReceivedView.as_view(),
        name="shop-fulfilment-received",
    ),
    path(
        "fulfilment-lines/<uuid:line_id>/cancel-repriced/",
        o.ShopCancelRepricedView.as_view(),
        name="shop-fulfilment-line-cancel-repriced",
    ),
    path(
        "orders/<uuid:order_id>/confirmation/",
        b.ShopOrderConfirmationView.as_view(),
        name="shop-order-confirmation",
    ),
    path("invoices/", b.ShopInvoicesView.as_view(), name="shop-invoices"),
    path("return-requests/", b.ShopReturnRequestsView.as_view(), name="shop-return-requests"),
    path(
        "return-requests/<uuid:request_id>/cancel/",
        b.ShopReturnRequestCancelView.as_view(),
        name="shop-return-request-cancel",
    ),
    path("invoices/<uuid:invoice_id>/", b.ShopInvoiceDetailView.as_view(), name="shop-invoice"),
    path(
        "invoices/<uuid:invoice_id>/pdf/", b.ShopInvoicePdfView.as_view(), name="shop-invoice-pdf"
    ),
    path(
        "credit-notes/<uuid:note_id>/pdf/",
        b.ShopCreditNotePdfView.as_view(),
        name="shop-credit-note-pdf",
    ),
    path("ledger/", b.ShopLedgerView.as_view(), name="shop-ledger"),
    path("account/", b.ShopAccountView.as_view(), name="shop-account"),
    path("payments/", b.ShopPaymentsView.as_view(), name="shop-payments"),
    path("payments/<uuid:payment_id>/", b.ShopPaymentDetailView.as_view(), name="shop-payment"),
    path(
        "payments/<uuid:payment_id>/receipt/",
        b.ShopReceiptView.as_view(),
        name="shop-payment-receipt",
    ),
    path(
        "checkout-attempts/<str:key>/",
        o.ShopCheckoutAttemptView.as_view(),
        name="shop-checkout-attempt",
    ),
]
