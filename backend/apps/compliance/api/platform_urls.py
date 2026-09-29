from django.urls import path

from apps.compliance.api import platform as v

urlpatterns = [
    path(
        "tenants/<uuid:tenant_id>/turnover-band/",
        v.TenantTurnoverView.as_view(),
        name="platform-tenant-turnover",
    ),
]
