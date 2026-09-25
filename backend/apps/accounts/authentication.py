"""Request authentication with per-request access checks (ADR-018, ADR-020, ADR-025).

On top of the signed token (``common.authentication``), every request re-checks:
- the token's tenant still exists and is ACTIVE (a suspension takes effect at once);
- a staff user still has an active membership in that tenant (deactivation takes effect at once);
- the token matches the host: tenant tokens only on their own subdomain, platform tokens only on
  the admin host. Generic and unknown hosts (server-side calls, future mobile API) are allowed.
"""

from typing import Any
from uuid import UUID

from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from apps.accounts.models import User
from apps.accounts.selectors import active_membership, role_codes
from apps.accounts.services import TenantSuspended
from apps.platform.models import Tenant
from apps.platform.selectors import tenant_info
from common.authentication import TENANT_CLAIM, TenantJWTAuthentication
from common.hosts import HostContext, HostKind


class SessionJWTAuthentication(TenantJWTAuthentication):
    def authenticate(self, request: Request) -> tuple[Any, Any] | None:
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        host: HostContext | None = getattr(request, "host_context", None)
        raw_tenant = token.get(TENANT_CLAIM)
        if raw_tenant:
            self._check_tenant_access(user, UUID(str(raw_tenant)), host)
        elif user.user_type != User.UserType.PLATFORM:
            raise AuthenticationFailed("This session is not valid.", code="token_not_valid")
        elif host is not None and host.kind == HostKind.TENANT:
            raise AuthenticationFailed("This session is not valid here.", code="wrong_host")
        return user, token

    @staticmethod
    def _check_tenant_access(user: User, tenant_id: UUID, host: HostContext | None) -> None:
        info = tenant_info(tenant_id)
        if info is None:
            raise AuthenticationFailed("This session is not valid.", code="token_not_valid")
        if info.status == Tenant.Status.SUSPENDED:
            raise TenantSuspended()
        if not info.is_active:
            raise AuthenticationFailed("This session is not valid.", code="token_not_valid")
        if host is not None and host.kind == HostKind.ADMIN:
            raise AuthenticationFailed("This session is not valid here.", code="wrong_host")
        if host is not None and host.kind == HostKind.TENANT and host.tenant_slug != info.slug:
            raise AuthenticationFailed("This session is not valid here.", code="wrong_host")
        if user.user_type == User.UserType.STAFF:
            membership = active_membership(user, tenant_id)
            if membership is None:
                raise AuthenticationFailed("You no longer have access.", code="membership_inactive")
            # Prime the per-request permission cache with the membership we just loaded.
            user.__dict__.setdefault("_perm_cache", {})[tenant_id] = role_codes(membership.role_id)
            user.__dict__["membership"] = membership
