"""``GET /api/v1/public/documents/{token}/`` on a tenant's address: the link in a WhatsApp or
email message (ADR-048 item 8). No sign-in; the token is the only key. A ready document
redirects to a 5-minute storage link; anything else is a short page a shop owner understands."""

from html import escape
from typing import Any

from django.http import HttpResponse, HttpResponseRedirect
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.notifications import links
from apps.notifications.context import distributor_name
from apps.platform.selectors import tenant_by_slug
from common.hosts import HostKind
from common.tenancy import tenant_context

L = links.LinkState
PAGES = {
    L.PREPARING: (200, "Your document is being prepared", "Please try again in a minute."),
    L.EXPIRED: (
        410,
        "This link has expired",
        "Sign in to the app to see your bills and receipts, or ask {name} for a new link.",
    ),
    L.REVOKED: (410, "This link no longer works", "Please ask {name} for a new link."),
    L.UNKNOWN: (404, "This link doesn't work", "Please check the link, or ask for a new one."),
}


def _page(state: str, name: str) -> HttpResponse:
    status, title, body = PAGES[state]
    refresh = '<meta http-equiv="refresh" content="15">' if state == L.PREPARING else ""
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{refresh}<title>{escape(title)}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:32rem;margin:3rem auto;"
        "padding:0 1rem;color:#1f2937;line-height:1.5}h1{font-size:1.25rem}</style></head>"
        f"<body><p>{escape(name)}</p><h1>{escape(title)}</h1>"
        f"<p>{escape(body.format(name=name or 'your distributor'))}</p></body></html>"
    )
    response = HttpResponse(html, status=status, content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


class PublicDocumentThrottle(AnonRateThrottle):
    scope = "public_documents"
    rate = "30/min"


class PublicDocumentView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicDocumentThrottle]

    @extend_schema(
        responses={
            302: OpenApiResponse(description="Redirect to a 5-minute link to the PDF"),
            200: OpenApiResponse(description="The document is being prepared (HTML)"),
            404: OpenApiResponse(description="Unknown link (HTML)"),
            410: OpenApiResponse(description="Expired or withdrawn link (HTML)"),
        },
        operation_id="public_document",
        tags=["public"],
    )
    def get(self, request: Request, token: str, *args: Any, **kwargs: Any) -> HttpResponse:
        host = request._request.host_context  # type: ignore[attr-defined]
        tenant = tenant_by_slug(host.tenant_slug) if host.kind == HostKind.TENANT else None
        if tenant is None:
            return _page(L.UNKNOWN, "")
        with tenant_context(tenant.pk):
            state, url = links.open_link(token)
        if state == L.READY:
            response = HttpResponseRedirect(url)
            response["Cache-Control"] = "no-store"
            response["Referrer-Policy"] = "no-referrer"
            return response
        return _page(state, distributor_name(tenant))
