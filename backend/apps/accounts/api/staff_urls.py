from django.urls import path

from apps.accounts.api import staff_views as views

urlpatterns = [
    path("staff/", views.StaffListView.as_view(), name="staff-list"),
    path("staff/invitations/", views.InvitationListCreateView.as_view(), name="staff-invitations"),
    path(
        "staff/invitations/<uuid:invitation_id>/resend/",
        views.InvitationResendView.as_view(),
        name="staff-invitation-resend",
    ),
    path(
        "staff/invitations/<uuid:invitation_id>/revoke/",
        views.InvitationRevokeView.as_view(),
        name="staff-invitation-revoke",
    ),
    path("staff/<uuid:membership_id>/", views.StaffDetailView.as_view(), name="staff-detail"),
    path("roles/", views.RoleListView.as_view(), name="roles-list"),
    path("permissions/", views.PermissionListView.as_view(), name="permissions-list"),
]
