from django.urls import path

from apps.planning.api import views as v

urlpatterns = [
    path("products/<uuid:product_id>/stats/", v.ProductStatsView.as_view(), name="product-stats"),
    path("planning/stats/refresh/", v.StatsRefreshView.as_view(), name="planning-stats-refresh"),
    path("reorder-suggestions/", v.SuggestionListView.as_view(), name="reorder-suggestions"),
    path(
        "reorder-suggestions/create-orders/",
        v.SuggestionCreateOrdersView.as_view(),
        name="reorder-suggestions-create-orders",
    ),
    path(
        "reorder-suggestions/apply-reorder-levels/",
        v.SuggestionApplyLevelsView.as_view(),
        name="reorder-suggestions-apply-levels",
    ),
    path(
        "reorder-suggestions/<uuid:suggestion_id>/",
        v.SuggestionDetailView.as_view(),
        name="reorder-suggestion",
    ),
]
