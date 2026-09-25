"""Request authentication with per-request access checks (ADR-018, ADR-020, ADR-025).

On top of the signed token (``common.authentication``), every request re-checks:
- the token's tenant still exists and is ACTIVE (a suspension takes effect at once);
- a staff user still has an active membership in that tenant, and a retailer login still belongs
  to that tenant and an active retailer (deactivation takes effect at once);
- the token matches the host: tenant tokens only on their own subdomain, platform tokens only on
  the admin host. Generic and unknown hosts (server-side calls, future mobile API) are allowed.
"""

from typing import Any
from uuid import UUID

from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request

from apps.accounts.impersonation import ImpersonationBlocked, ImpersonationReadOnly, open_session
from apps.accounts.models import ImpersonationSession, User
from apps.accounts.selectors import active_membership, retailer_login_for_tenant, role_codes
from apps.accounts.services import TenantUnavailable
from apps.platform.models import Tenant
from apps.platform.selectors import tenant_info
from common.authentication import (
    IMPERSONATION_SESSION_CLAIM,
    IMPERSONATOR_CLAIM,
    TENANT_CLAIM,
    TenantJWTAuthentication,
)
from common.hosts import HostContext, HostKind


class SessionJWTAuthentication(TenantJWTAuthentication):
    def authenticate(self, request: Request) -> tuple[Any, Any] | None:
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        host: HostContext | None = getattr(request, "host_context", None)
        raw_tenant = token.get(TENANT_CLAIM)
        impersonating = bool(token.get(IMPERSONATION_SESSION_CLAIM))
        if raw_tenant:
            self._check_tenant_access(user, UUID(str(raw_tenant)), host, impersonating)
            if impersonating:
                self._check_impersonation(request, user, token, UUID(str(raw_tenant)))
        elif user.user_type != User.UserType.PLATFORM:
            raise AuthenticationFailed("This session is not valid.", code="token_not_valid")
        elif host is not None and host.kind == HostKind.TENANT:
            raise AuthenticationFailed("This session is not valid here.", code="wrong_host")
        return user, token

    @staticmethod
    def _check_impersonation(request: Request, user: User, token: Any, tenant_id: UUID) -> None:
        """ADR-029: the session must still be open; READ-ONLY refuses writes; endpoints marked
        ``impersonation_blocked`` refuse writes in every mode."""
        session = open_session(UUID(str(token[IMPERSONATION_SESSION_CLAIM])), tenant_id)
        if (
            session is None
            or session.target_user_id != user.pk
            or str(session.impersonator_id) != str(token.get(IMPERSONATOR_CLAIM))
        ):
            raise AuthenticationFailed(
                "This support session has ended.", code="impersonation_ended"
            )
        user.__dict__["impersonation_session"] = session
        view = (getattr(request, "parser_context", None) or {}).get("view")
        if getattr(view, "impersonation_control", False):
            # act/end record their own audit events; skip the generic write entry.
            request._request.impersonation_control = True  # type: ignore[attr-defined]
            return
        if request.method in SAFE_METHODS:
            return
        if getattr(view, "impersonation_blocked", False):
            raise ImpersonationBlocked()
        if session.mode != ImpersonationSession.Mode.ACT:
            raise ImpersonationReadOnly()

    @staticmethod
    def _check_tenant_access(
        user: User, tenant_id: UUID, host: HostContext | None, impersonating: bool = False
    ) -> None:
        info = tenant_info(tenant_id)
        if info is None:
            raise AuthenticationFailed("This session is not valid.", code="token_not_valid")
        if info.status != Tenant.Status.ACTIVE and not impersonating:
            raise TenantUnavailable()  # ADR-018: support may still look at a suspended tenant
        if host is not None and host.kind == HostKind.ADMIN:
            raise AuthenticationFailed("This session is not valid here.", code="wrong_host")
        if host is not None and host.kind == HostKind.TENANT and host.tenant_slug != info.slug:
            raise AuthenticationFailed("This session is not valid here.", code="wrong_host")
        if user.user_type == User.UserType.RETAILER and (
            user.tenant_id != tenant_id
            or retailer_login_for_tenant(user.phone or "", tenant_id) is None
        ):
            raise AuthenticationFailed("You no longer have access.", code="retailer_inactive")
        if user.user_type == User.UserType.STAFF:
            membership = active_membership(user, tenant_id)
            if membership is None:
                raise AuthenticationFailed("You no longer have access.", code="membership_inactive")
            # Prime the per-request permission cache with the membership we just loaded.
            user.__dict__.setdefault("_perm_cache", {})[tenant_id] = role_codes(membership.role_id)
            user.__dict__["membership"] = membership
