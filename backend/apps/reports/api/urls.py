from django.urls import path

from apps.reports.api import views as v

urlpatterns = [
    path("reports/", v.ReportListView.as_view(), name="reports"),
    path("reports/<str:code>/", v.ReportView.as_view(), name="report"),
    path("reports/<str:code>/export/", v.ReportExportView.as_view(), name="report-export"),
    path("report-runs/", v.ReportRunListView.as_view(), name="report-runs"),
    path("report-runs/<uuid:run_id>/", v.ReportRunView.as_view(), name="report-run"),
]
