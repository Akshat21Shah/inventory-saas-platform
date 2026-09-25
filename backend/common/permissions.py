"""Base DRF permission classes. Every endpoint declares its permission on the server (CLAUDE.md §4).

Permission codes (e.g. ``orders.accept``) are resolved by ``User.has_permission_code`` which Phase 1
implements from Membership → Role → Permission. Until then the check fails closed.
"""

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView


def user_has_permission(user: Any, code: str) -> bool:
    checker = getattr(user, "has_permission_code", None)
    return bool(user and user.is_authenticated and checker is not None and checker(code))


class HasPermission(BasePermission):
    """Checks ``view.required_permission`` (str) or ``view.required_permissions[method]``."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        per_method: dict[str, str] | None = getattr(view, "required_permissions", None)
        code: str | None = (per_method or {}).get(request.method or "", None) or getattr(
            view, "required_permission", None
        )
        if not code:
            return False  # fail closed: a view using HasPermission must declare a code
        return user_has_permission(request.user, code)


class _UserTypePermission(BasePermission):
    user_type: str = ""

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return bool(
            user and user.is_authenticated and getattr(user, "user_type", None) == self.user_type
        )


class IsPlatformUser(_UserTypePermission):
    user_type = "PLATFORM"


class IsTenantStaff(_UserTypePermission):
    user_type = "STAFF"


class IsRetailer(_UserTypePermission):
    user_type = "RETAILER"


class IsStaffOrPlatformUser(BasePermission):
    """Email + password accounts (distributor staff and super admins), not retailers."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "user_type", None) in ("STAFF", "PLATFORM")
        )


class StaffReadsOrHasPermission(HasPermission):
    """Any staff member of the active tenant may read; changes need the declared permission
    (``required_permissions[method]`` or ``required_permission``)."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            user = request.user
            return bool(
                user and user.is_authenticated and getattr(user, "user_type", None) == "STAFF"
            )
        return super().has_permission(request, view)
