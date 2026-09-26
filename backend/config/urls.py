from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

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
    path("", include("apps.platform.api.tenant_urls")),
    path("", include("apps.dataio.api.urls")),
    path("", include("apps.catalog.api.urls")),
    path("", include("apps.retailers.api.urls")),
    path("", include("apps.pricing.api.urls")),
    path("", include("apps.inventory.api.urls")),
    path("shop/", include("apps.shop.api.urls")),
    path("public/states/", PublicStatesView.as_view(), name="public-states"),
]

urlpatterns = [
    path("health/live", health.live, name="health-live"),
    path("health/ready", health.ready, name="health-ready"),
    path("api/v1/", include(api_v1)),
    path("django-admin/", admin.site.urls),
]
