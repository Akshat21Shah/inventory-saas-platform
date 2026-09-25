from django.urls import path

from apps.accounts.api import views

urlpatterns = [
    path("staff/login/", views.StaffLoginView.as_view(), name="auth-staff-login"),
    path("staff/choose-tenant/", views.ChooseTenantView.as_view(), name="auth-staff-choose-tenant"),
    path("handoff/exchange/", views.HandoffExchangeView.as_view(), name="auth-handoff-exchange"),
    path("token/refresh/", views.TokenRefreshView.as_view(), name="auth-token-refresh"),
    path("logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("me/", views.MeView.as_view(), name="auth-me"),
]
