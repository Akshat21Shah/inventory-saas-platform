from django.urls import path

from apps.notifications.api import platform as v

urlpatterns = [
    path(
        "notification-templates/",
        v.PlatformTemplatesView.as_view(),
        name="platform-notification-templates",
    ),
    path(
        "notification-templates/preview/",
        v.PlatformTextPreviewView.as_view(),
        name="platform-notification-template-preview",
    ),
    path(  # before the <event>/<channel> pattern, which would match it
        "notification-templates/<uuid:template_id>/approval/",
        v.PlatformTemplateApprovalView.as_view(),
        name="platform-notification-template-approval",
    ),
    path(
        "notification-templates/<str:event>/<str:channel>/",
        v.PlatformTemplateView.as_view(),
        name="platform-notification-template",
    ),
    path(
        "notification-failures/",
        v.PlatformFailuresView.as_view(),
        name="platform-notification-failures",
    ),
    path(
        "notification-failures/<uuid:notification_id>/retry/",
        v.PlatformFailureRetryView.as_view(),
        name="platform-notification-failure-retry",
    ),
]
