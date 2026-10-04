"""The app's browser payment page (ADR-061 item 9): its session and its one checkout."""

from django.urls import path

from apps.payments.api import browser as b

urlpatterns = [
    path("session/", b.PaySessionView.as_view(), name="pay-session"),
    path("checkout/", b.PayCheckoutView.as_view(), name="pay-checkout"),
    path("checkout/outcome/", b.PayCheckoutOutcomeView.as_view(), name="pay-checkout-outcome"),
]
