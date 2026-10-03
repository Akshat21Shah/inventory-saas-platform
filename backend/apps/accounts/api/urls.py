from django.urls import path

from apps.accounts.api import live, staff_views, views

urlpatterns = [
    path("staff/login/", views.StaffLoginView.as_view(), name="auth-staff-login"),
    path("staff/choose-tenant/", views.ChooseTenantView.as_view(), name="auth-staff-choose-tenant"),
    path("handoff/exchange/", views.HandoffExchangeView.as_view(), name="auth-handoff-exchange"),
    path("token/refresh/", views.TokenRefreshView.as_view(), name="auth-token-refresh"),
    path("logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("me/", views.MeView.as_view(), name="auth-me"),
    path("ws-ticket/", live.WsTicketView.as_view(), name="auth-ws-ticket"),
    path("staff/mfa/verify/", views.StaffMfaVerifyView.as_view(), name="auth-staff-mfa-verify"),
    path(
        "staff/mfa/enrol/start/",
        views.StaffMfaEnrolStartView.as_view(),
        name="auth-staff-mfa-enrol-start",
    ),
    path(
        "staff/mfa/enrol/confirm/",
        views.StaffMfaEnrolConfirmView.as_view(),
        name="auth-staff-mfa-enrol-confirm",
    ),
    path("mfa/setup/", views.MfaSetupView.as_view(), name="auth-mfa-setup"),
    path("mfa/confirm/", views.MfaConfirmView.as_view(), name="auth-mfa-confirm"),
    path("mfa/disable/", views.MfaDisableView.as_view(), name="auth-mfa-disable"),
    path("mfa/recovery-codes/", views.RecoveryCodesView.as_view(), name="auth-mfa-recovery-codes"),
    path("password/forgot/", views.PasswordForgotView.as_view(), name="auth-password-forgot"),
    path("password/reset/", views.PasswordResetView.as_view(), name="auth-password-reset"),
    path("password/change/", views.PasswordChangeView.as_view(), name="auth-password-change"),
    path(
        "retailer/otp/request/",
        views.RetailerOtpRequestView.as_view(),
        name="auth-retailer-otp-request",
    ),
    path(
        "retailer/otp/verify/",
        views.RetailerOtpVerifyView.as_view(),
        name="auth-retailer-otp-verify",
    ),
    path(
        "retailer/choose-account/",
        views.RetailerChooseAccountView.as_view(),
        name="auth-retailer-choose-account",
    ),
    path(
        "invitations/preview/",
        staff_views.InvitationPreviewView.as_view(),
        name="auth-invitation-preview",
    ),
    path(
        "invitations/accept/",
        staff_views.InvitationAcceptView.as_view(),
        name="auth-invitation-accept",
    ),
    path("impersonation/act/", views.ImpersonationActView.as_view(), name="auth-impersonation-act"),
    path("impersonation/end/", views.ImpersonationEndView.as_view(), name="auth-impersonation-end"),
]
