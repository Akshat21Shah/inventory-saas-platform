"""Request context: request id, host classification, and a clean tenant/user context per request."""

import re
import uuid
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from common.context import (
    RequestMeta,
    actor_var,
    request_id_var,
    request_meta_var,
    tenant_id_var,
    user_id_var,
)
from common.hosts import classify_host
from common.net import client_ip

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestContextMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        meta = RequestMeta(
            ip=client_ip(request), user_agent=request.headers.get("User-Agent", "")[:500]
        )
        tokens = (
            request_id_var.set(request_id),
            tenant_id_var.set(None),
            user_id_var.set(None),
            request_meta_var.set(meta),
            actor_var.set(None),
        )
        forwarded_host = request.headers.get("X-Forwarded-Host", "").split(",")[0].strip()
        request.host_context = classify_host(forwarded_host or request.get_host())  # type: ignore[attr-defined]
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(tokens[0])
            tenant_id_var.reset(tokens[1])
            user_id_var.reset(tokens[2])
            request_meta_var.reset(tokens[3])
            actor_var.reset(tokens[4])
        response["X-Request-ID"] = request_id
        return response
