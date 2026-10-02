from django.urls import path

from apps.insights.api import views as v

urlpatterns = [
    path("shop-activity/", v.ActivityListView.as_view(), name="shop-activity"),
    path("shop-activity/refresh/", v.ActivityRefreshView.as_view(), name="shop-activity-refresh"),
    path(
        "retailers/<uuid:retailer_id>/activity/",
        v.ShopActivityView.as_view(),
        name="retailer-activity",
    ),
    path(
        "retailers/<uuid:retailer_id>/contacts/",
        v.ShopContactCreateView.as_view(),
        name="retailer-contacts",
    ),
]
