from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from common import health
from common.api import MetaView

api_v1: list[URLPattern | URLResolver] = [
    path("meta/", MetaView.as_view(), name="meta"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("auth/", include("apps.accounts.api.urls")),
    path("", include("apps.accounts.api.staff_urls")),
]

urlpatterns = [
    path("health/live", health.live, name="health-live"),
    path("health/ready", health.ready, name="health-ready"),
    path("api/v1/", include(api_v1)),
    path("django-admin/", admin.site.urls),
]
