"""DRF authentication that activates the tenant carried in the signed JWT (ADR-002, ADR-020)."""

from typing import Any
from uuid import UUID

from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication

from common.context import user_id_var
from common.tenancy import activate_tenant

TENANT_CLAIM = "tid"


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
        raw_tenant = token.get(TENANT_CLAIM)
        activate_tenant(UUID(str(raw_tenant)) if raw_tenant else None)
        return user, token
