from django.urls import path

from apps.notifications.api import shop as v

urlpatterns = [
    path("notifications/", v.ShopInboxView.as_view(), name="shop-notifications"),
    path(
        "notifications/unread-count/",
        v.ShopUnreadCountView.as_view(),
        name="shop-notifications-unread",
    ),
    path(
        "notifications/read-all/",
        v.ShopMarkAllReadView.as_view(),
        name="shop-notifications-read-all",
    ),
    path(
        "notifications/<uuid:notification_id>/read/",
        v.ShopMarkReadView.as_view(),
        name="shop-notification-read",
    ),
    path(
        "notification-preferences/",
        v.ShopPreferencesView.as_view(),
        name="shop-notification-preferences",
    ),
    path("whatsapp-consent/", v.ShopConsentView.as_view(), name="shop-whatsapp-consent"),
    path(
        "whatsapp-consent/prompted/",
        v.ShopConsentPromptedView.as_view(),
        name="shop-whatsapp-consent-prompted",
    ),
    path("announcements/", v.ShopAnnouncementsView.as_view(), name="shop-announcements"),
]
