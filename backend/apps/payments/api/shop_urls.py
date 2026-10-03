from django.urls import path

from apps.payments.api import browser as b
from apps.payments.api import online as v

urlpatterns = [
    path("payments/checkout/", v.ShopCheckoutView.as_view(), name="shop-checkout"),
    path(
        "payments/checkout/<uuid:intent_id>/",
        v.ShopCheckoutDetailView.as_view(),
        name="shop-checkout-detail",
    ),
    path(
        "payments/checkout/<uuid:intent_id>/browser/",
        b.ShopCheckoutBrowserView.as_view(),
        name="shop-checkout-browser",
    ),
]
