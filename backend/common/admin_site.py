"""Django admin as an internal, read-only ops tool for super admins (spec 5.1, PLAN 1.13).

- Only PLATFORM super admins, only on the admin host.
- Sign-in needs the password and the TOTP code, with the same rate limits and lockout as the API.
- Everything is read-only and read through the audited platform (BYPASSRLS) alias; changes go
  through the platform UI/API, which validates and audits them.
"""

from typing import Any

from django import forms
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.db.models import Model, QuerySet
from django.http import HttpRequest
from django.utils.translation import gettext as _

from common.hosts import HostKind
from common.platform_db import platform_db


def _on_admin_host(request: HttpRequest) -> bool:
    host = getattr(request, "host_context", None)
    return host is not None and host.kind == HostKind.ADMIN


class PlatformAdminLoginForm(AdminAuthenticationForm):
    otp = forms.CharField(label="Code from your authenticator app", max_length=10)

    def clean(self) -> dict[str, Any]:
        from apps.accounts import mfa
        from apps.accounts.services import InvalidCredentials, verify_password_login
        from common.context import request_meta_var

        email = self.cleaned_data.get("username") or ""
        password = self.cleaned_data.get("password") or ""
        meta = request_meta_var.get()
        error = forms.ValidationError(
            _("Sign-in failed. Check your email, password and code."), code="invalid_login"
        )
        if self.request is None or not _on_admin_host(self.request):
            raise error
        try:
            user = verify_password_login(email, password, meta.ip if meta else None)
        except InvalidCredentials as exc:
            raise error from exc
        if user.user_type != "PLATFORM" or not user.is_superuser or not user.totp_enabled:
            raise error
        if not mfa.verify_user_totp(user, self.cleaned_data.get("otp") or ""):
            raise error
        self.user_cache = user
        return self.cleaned_data


class PlatformAdminSite(admin.AdminSite):
    site_header = "Inventory Platform operations (read-only)"
    site_title = "Platform operations"
    login_form = PlatformAdminLoginForm

    def has_permission(self, request: HttpRequest) -> bool:
        user = request.user
        return bool(
            user.is_active
            and user.is_authenticated
            and getattr(user, "user_type", None) == "PLATFORM"
            and user.is_superuser
            and _on_admin_host(request)
        )


class ReadOnlyPlatformAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Read-only, cross-tenant view through the audited platform alias."""

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        qs: QuerySet[Any] = self.model._base_manager.using(platform_db("django_admin"))
        ordering = self.get_ordering(request)
        return qs.order_by(*ordering) if ordering else qs

    def has_add_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        return False

    def has_view_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        return self.admin_site.has_permission(request)

    def has_module_permission(self, request: HttpRequest) -> bool:
        return self.admin_site.has_permission(request)
