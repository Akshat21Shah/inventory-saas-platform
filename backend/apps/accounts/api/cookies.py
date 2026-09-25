"""Refresh-token cookie and the same-origin guard for cookie-authenticated endpoints (ADR-025)."""

from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.tokens import IssuedTokens
from common.error_codes import ErrorCode
from common.errors import DomainError


class CrossOriginRefused(DomainError):
    status_code = 403
    code = ErrorCode.PERMISSION_DENIED
    default_message = "This request was blocked."


def set_refresh_cookie(response: Response, tokens: IssuedTokens) -> None:
    """httpOnly, SameSite=Lax, host-only (no Domain: never shared with other subdomains)."""
    max_age = int((tokens.refresh_expires_at - timezone.now()).total_seconds())
    response.set_cookie(
        settings.AUTH_REFRESH_COOKIE_NAME,
        tokens.refresh,
        max_age=max(max_age, 0),
        path=settings.AUTH_REFRESH_COOKIE_PATH,
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="Lax",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        settings.AUTH_REFRESH_COOKIE_NAME, path=settings.AUTH_REFRESH_COOKIE_PATH, samesite="Lax"
    )


def read_refresh_cookie(request: Request) -> str | None:
    value: str | None = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
    return value


def _request_hostname(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-Host", "").split(",")[0].strip()
    return (forwarded or request.get_host()).split(":", 1)[0].lower()


def require_same_origin(request: Request) -> None:
    """CSRF defence when the refresh cookie authenticates the request: a custom header that
    cross-site forms cannot send, and an Origin whose host matches the request host."""
    if request.headers.get("X-Requested-With") != "fetch":
        raise CrossOriginRefused()
    origin = request.headers.get("Origin", "")
    if not origin or (urlparse(origin).hostname or "").lower() != _request_hostname(request):
        raise CrossOriginRefused()
