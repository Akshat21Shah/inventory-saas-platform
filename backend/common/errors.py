"""Domain error base class. Deliberately free of DRF imports so models/services can use it."""

from typing import Any

from django.utils.functional import Promise
from django.utils.translation import gettext_lazy

from common.error_codes import ErrorCode


def plain(value: Any) -> Any:
    """Translated text as plain strings, in the language active now (the request's), so errors
    can be stored as JSON and don't change language later."""
    if isinstance(value, Promise):
        return str(value)
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [plain(item) for item in value]
    return value


class DomainError(Exception):
    """Raise from services for expected business failures. Subclass per error family."""

    status_code: int = 400
    code: str = ErrorCode.VALIDATION_ERROR
    default_message: str | Promise = gettext_lazy("The request could not be completed.")
    headers: dict[str, str] | None = None  # extra response headers (e.g. Retry-After)

    def __init__(
        self,
        message: str | Promise | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message: str = str(message or self.default_message)
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details: dict[str, Any] = plain(details or {})
        super().__init__(self.message)


class InvalidFields(DomainError):
    """Field-level validation failure raised by services: ``{"fields": {name: [messages]}}``."""

    status_code = 400
    code = ErrorCode.VALIDATION_ERROR
    default_message = gettext_lazy("Some fields need attention.")

    def __init__(
        self, fields: dict[str, list[str]] | dict[str, Any], message: str | None = None
    ) -> None:
        super().__init__(message, details={"fields": fields})


class NotFound(DomainError):
    """A record the caller asked for does not exist in their tenant (also for other tenants'
    records: never reveal that they exist)."""

    status_code = 404
    code = ErrorCode.NOT_FOUND
    default_message = gettext_lazy("We couldn't find what you were looking for.")
