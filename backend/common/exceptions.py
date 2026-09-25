"""Domain errors and the DRF exception handler producing the standard error envelope:

    {"error": {"code": "CREDIT_LIMIT_EXCEEDED", "message": "...", "details": {...}}}

Every handled error marks the request transaction for rollback (ATOMIC_REQUESTS), so a converted
error response can never commit partial writes.
"""

import logging
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.views import set_rollback

from common.error_codes import ErrorCode
from common.errors import DomainError

logger = logging.getLogger(__name__)


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": str(code), "message": message, "details": details or {}}}


_DRF_CODE_MAP: dict[type[drf_exceptions.APIException], ErrorCode] = {
    drf_exceptions.ValidationError: ErrorCode.VALIDATION_ERROR,
    drf_exceptions.ParseError: ErrorCode.PARSE_ERROR,
    drf_exceptions.NotAuthenticated: ErrorCode.NOT_AUTHENTICATED,
    drf_exceptions.AuthenticationFailed: ErrorCode.AUTHENTICATION_FAILED,
    drf_exceptions.PermissionDenied: ErrorCode.PERMISSION_DENIED,
    drf_exceptions.NotFound: ErrorCode.NOT_FOUND,
    drf_exceptions.MethodNotAllowed: ErrorCode.METHOD_NOT_ALLOWED,
    drf_exceptions.NotAcceptable: ErrorCode.NOT_ACCEPTABLE,
    drf_exceptions.UnsupportedMediaType: ErrorCode.UNSUPPORTED_MEDIA_TYPE,
    drf_exceptions.Throttled: ErrorCode.THROTTLED,
}


def _code_for(exc: drf_exceptions.APIException) -> str:
    for exc_type, code in _DRF_CODE_MAP.items():
        if isinstance(exc, exc_type):
            return code
    return str(exc.default_code).upper()


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, DomainError):
        set_rollback()
        return Response(error_body(exc.code, exc.message, exc.details), status=exc.status_code)

    if isinstance(exc, Http404):
        exc = drf_exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = drf_exceptions.PermissionDenied()

    response = drf_exception_handler(exc, context)  # calls set_rollback() for APIException
    if response is None:
        # Unexpected error: log with request/tenant context (logging filter); never leak details.
        set_rollback()
        logger.exception("Unhandled API error", exc_info=exc)
        return Response(
            error_body(ErrorCode.INTERNAL_ERROR, "Something went wrong. Please try again."),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    assert isinstance(exc, drf_exceptions.APIException)
    if isinstance(exc, drf_exceptions.ValidationError):
        details = {"fields": response.data}
        message = "Some fields need attention."
    else:
        details = {}
        message = str(exc.detail) if not isinstance(exc.detail, (list, dict)) else "Request failed."
    response.data = error_body(_code_for(exc), message, details)
    return response
