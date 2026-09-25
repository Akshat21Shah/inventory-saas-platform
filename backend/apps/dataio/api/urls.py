from django.urls import path
from drf_spectacular.utils import extend_schema, extend_schema_view

from apps.dataio.api import views as v

ProductExport = extend_schema_view(get=extend_schema(operation_id="products_export"))(
    v.ProductExportView
)

urlpatterns = [
    path("imports/", v.ImportListCreateView.as_view(), name="imports"),
    path("imports/templates/<str:kind>/", v.ImportTemplateView.as_view(), name="import-template"),
    path("imports/<uuid:job_id>/", v.ImportDetailView.as_view(), name="import-detail"),
    path("imports/<uuid:job_id>/commit/", v.ImportCommitView.as_view(), name="import-commit"),
    path("imports/<uuid:job_id>/report/", v.ImportReportView.as_view(), name="import-report"),
    path("products/export/", ProductExport.as_view(), name="products-export"),
]
