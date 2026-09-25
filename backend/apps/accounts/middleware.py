"""Audit every successful write made during a support session (ADR-029)."""

from collections.abc import Callable

from django.db import transaction
from django.http import HttpRequest, HttpResponse

from apps.audit import services as audit
from common.context import actor_var
from common.tenancy import get_current_tenant_id

SAFE = frozenset({"GET", "HEAD", "OPTIONS"})


class ImpersonationAuditMiddleware:
    """Runs inside RequestContextMiddleware, so the actor and tenant of the request are known."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        actor = actor_var.get()
        if (
            actor is not None
            and actor.impersonator_id is not None
            and request.method not in SAFE
            and response.status_code < 400
            and not getattr(request, "impersonation_control", False)
        ):
            tenant_id = get_current_tenant_id()
            with transaction.atomic():
                audit.record(
                    "impersonation.write",
                    target_type="request",
                    target_repr=f"{request.method} {request.path}"[:200],
                    tenant_id=tenant_id,
                    metadata={
                        "method": request.method,
                        "path": request.path,
                        "status": response.status_code,
                    },
                )
        return response
