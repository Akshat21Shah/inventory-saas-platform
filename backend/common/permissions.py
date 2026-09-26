"""Base DRF permission classes. Every endpoint declares its permission on the server (CLAUDE.md §4).

Permission codes (e.g. ``orders.accept``) are resolved by ``User.has_permission_code`` which Phase 1
implements from Membership → Role → Permission. Until then the check fails closed.
"""

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView


class AnyOf(tuple[str, ...]):
    """A requirement met by any one of these codes, e.g. ``AnyOf(("products.manage",
    "stock.adjust"))``."""


class AllOf(tuple[str, ...]):
    """A requirement that needs every one of these codes."""


Requirement = str | AnyOf | AllOf


def codes_of(requirement: Requirement) -> tuple[str, ...]:
    return (requirement,) if isinstance(requirement, str) else tuple(requirement)


def user_has_permission(user: Any, code: Requirement) -> bool:
    checker = getattr(user, "has_permission_code", None)
    if not (user and user.is_authenticated and checker is not None):
        return False
    if isinstance(code, AnyOf):
        return any(checker(c) for c in code)
    if isinstance(code, AllOf):
        return all(checker(c) for c in code)
    return bool(checker(code))


class HasPermission(BasePermission):
    """Checks ``view.required_permission`` or ``view.required_permissions[method]``: a code, or
    ``AnyOf`` / ``AllOf`` several codes."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        per_method: dict[str, Requirement] | None = getattr(view, "required_permissions", None)
        code: Requirement | None = (per_method or {}).get(request.method or "", None) or getattr(
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
