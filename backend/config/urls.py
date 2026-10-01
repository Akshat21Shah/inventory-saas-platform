from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.notifications.api.public import PublicDocumentView
from apps.payments.api.online import GatewayWebhookView, MockGatewayPageView
from apps.platform.api.views import PublicStatesView
from common import health
from common.api import MetaView

api_v1: list[URLPattern | URLResolver] = [
    path("meta/", MetaView.as_view(), name="meta"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("auth/", include("apps.accounts.api.urls")),
    path("", include("apps.accounts.api.staff_urls")),
    path("platform/", include("apps.platform.api.urls")),
    path("platform/", include("apps.notifications.api.platform_urls")),
    path("platform/", include("apps.compliance.api.platform_urls")),
    path("platform/", include("apps.search.api.platform_urls")),
    path("", include("apps.platform.api.tenant_urls")),
    path("", include("apps.dataio.api.urls")),
    path("", include("apps.catalog.api.urls")),
    path("", include("apps.retailers.api.urls")),
    path("", include("apps.pricing.api.urls")),
    path("", include("apps.inventory.api.urls")),
    path("", include("apps.orders.api.urls")),
    path("", include("apps.billing.api.urls")),
    path("", include("apps.ledger.api.urls")),
    path("", include("apps.payments.api.urls")),
    path("", include("apps.notifications.api.urls")),
    path("", include("apps.compliance.api.urls")),
    path("", include("apps.reports.api.urls")),
    path("", include("apps.search.api.urls")),
    path("", include("apps.planning.api.urls")),
    path("shop/", include("apps.shop.api.urls")),
    path("shop/", include("apps.notifications.api.shop_urls")),
    path("shop/", include("apps.payments.api.shop_urls")),
    path(
        "webhooks/payments/<str:provider>/<str:token>/",
        GatewayWebhookView.as_view(),
        name="payment-webhook",
    ),
    # DEV ONLY: the mock gateway's checkout page (refused unless mock integrations are allowed).
    path("dev/mock-gateway/<str:order_id>/", MockGatewayPageView.as_view(), name="mock-gateway"),
    path("public/states/", PublicStatesView.as_view(), name="public-states"),
    path("public/documents/<str:token>/", PublicDocumentView.as_view(), name="public-document"),
]

urlpatterns = [
    path("health/live", health.live, name="health-live"),
    path("health/ready", health.ready, name="health-ready"),
    path("api/v1/", include(api_v1)),
    path("django-admin/", admin.site.urls),
]
