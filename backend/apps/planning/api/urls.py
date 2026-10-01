from django.urls import path

from apps.planning.api import views as v

urlpatterns = [
    path("products/<uuid:product_id>/stats/", v.ProductStatsView.as_view(), name="product-stats"),
    path("planning/stats/refresh/", v.StatsRefreshView.as_view(), name="planning-stats-refresh"),
]
