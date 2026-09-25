"""DRF authentication that activates the tenant carried in the signed JWT (ADR-002, ADR-020)."""

from typing import Any
from uuid import UUID

from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication

from common.context import Actor, actor_var, user_id_var
from common.tenancy import activate_tenant

TENANT_CLAIM = "tid"
# Impersonation claims (ADR-029), issued only by the impersonation service.
IMPERSONATION_SESSION_CLAIM = "imp"
IMPERSONATOR_CLAIM = "imp_by"
IMPERSONATION_MODE_CLAIM = "imp_mode"


def _uuid_or_none(value: Any) -> UUID | None:
    return UUID(str(value)) if value else None


class TenantJWTAuthentication(JWTAuthentication):
    """JWT auth that activates the tenant carried in the token's ``tid`` claim.

    Phase 1 issues tokens whose ``tid`` is resolved from the user's membership/retailer account and
    the request host (ADR-020); this class only trusts the signed claim.
    """

    def authenticate(self, request: Request) -> tuple[Any, Any] | None:
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        user_id_var.set(str(user.pk))
        actor_var.set(
            Actor(
                user_id=user.pk,
                actor_type=getattr(user, "user_type", ""),
                impersonator_id=_uuid_or_none(token.get(IMPERSONATOR_CLAIM)),
                impersonation_session_id=_uuid_or_none(token.get(IMPERSONATION_SESSION_CLAIM)),
            )
        )
        raw_tenant = token.get(TENANT_CLAIM)
        activate_tenant(UUID(str(raw_tenant)) if raw_tenant else None)
        return user, token
