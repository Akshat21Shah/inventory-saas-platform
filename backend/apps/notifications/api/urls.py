from django.urls import path

from apps.notifications.api import views as v

urlpatterns = [
    path("notifications/", v.InboxView.as_view(), name="notifications"),
    path("notifications/unread-count/", v.UnreadCountView.as_view(), name="notifications-unread"),
    path("notifications/read-all/", v.MarkAllReadView.as_view(), name="notifications-read-all"),
    path(
        "notifications/<uuid:notification_id>/read/",
        v.MarkReadView.as_view(),
        name="notification-read",
    ),
    path(
        "notification-preferences/",
        v.StaffPreferencesView.as_view(),
        name="notification-preferences",
    ),
    path("notification-rules/", v.RulesView.as_view(), name="notification-rules"),
    path("notification-rules/<str:event>/", v.EventRulesView.as_view(), name="notification-rule"),
    path(
        "notification-templates/preview/",
        v.TextPreviewView.as_view(),
        name="notification-template-preview",
    ),
    path(
        "notification-templates/<str:event>/",
        v.EventTextsView.as_view(),
        name="notification-templates",
    ),
    path(
        "notification-templates/<str:event>/<str:channel>/",
        v.EventTextView.as_view(),
        name="notification-template",
    ),
    path("notification-deliveries/", v.DeliveriesView.as_view(), name="notification-deliveries"),
    path(
        "notification-deliveries/counts/",
        v.DeliveryCountsView.as_view(),
        name="notification-delivery-counts",
    ),
    path(
        "notification-deliveries/<uuid:notification_id>/",
        v.DeliveryDetailView.as_view(),
        name="notification-delivery",
    ),
    path(
        "notification-deliveries/<uuid:notification_id>/retry/",
        v.DeliveryRetryView.as_view(),
        name="notification-delivery-retry",
    ),
    path("announcements/", v.AnnouncementsView.as_view(), name="announcements"),
    path(
        "announcements/<uuid:announcement_id>/",
        v.AnnouncementDetailView.as_view(),
        name="announcement",
    ),
    path("document-links/", v.DocumentLinksView.as_view(), name="document-links"),
    path(
        "document-links/revoke/",
        v.DocumentLinksRevokeView.as_view(),
        name="document-links-revoke",
    ),
    path(
        "retailers/<uuid:retailer_id>/reminder-pause/",
        v.ReminderPauseView.as_view(),
        name="retailer-reminder-pause",
    ),
    path(
        "retailers/<uuid:retailer_id>/whatsapp-consent/",
        v.RetailerConsentView.as_view(),
        name="retailer-whatsapp-consent",
    ),
    path(
        "tax/upcoming-rate-changes/",
        v.UpcomingRateChangesView.as_view(),
        name="tax-upcoming-rate-changes",
    ),
]
