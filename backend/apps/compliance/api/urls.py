from django.urls import path

from apps.compliance.api import views as v

urlpatterns = [
    path("settings/gst-credentials/", v.GstCredentialsView.as_view(), name="gst-credentials"),
    path(
        "settings/gst-credentials/verify/",
        v.GstCredentialsVerifyView.as_view(),
        name="gst-credentials-verify",
    ),
]
