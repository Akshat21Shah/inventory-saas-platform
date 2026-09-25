from django.contrib import admin
from django.contrib.auth.models import Group
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.accounts.models import ImpersonationSession, Membership, User
from common.admin_site import ReadOnlyPlatformAdmin

# Editable third-party registrations have no place in a read-only ops tool (and token rows are
# credentials).
for _model in (Group, OutstandingToken, BlacklistedToken):
    if admin.site.is_registered(_model):
        admin.site.unregister(_model)


@admin.register(User)
class UserAdmin(ReadOnlyPlatformAdmin):
    list_display = (
        "email",
        "phone",
        "user_type",
        "tenant",
        "is_active",
        "totp_enabled",
        "created_at",
    )
    search_fields = ("email", "phone", "full_name")
    list_filter = ("user_type", "is_active", "totp_enabled")
    exclude = ("password", "totp_secret", "totp_last_step", "groups", "user_permissions")


@admin.register(Membership)
class MembershipAdmin(ReadOnlyPlatformAdmin):
    list_display = ("user", "tenant", "role", "is_active", "joined_at")
    list_filter = ("is_active",)


@admin.register(ImpersonationSession)
class ImpersonationSessionAdmin(ReadOnlyPlatformAdmin):
    list_display = ("impersonator", "target_user", "tenant", "mode", "created_at", "ended_at")
