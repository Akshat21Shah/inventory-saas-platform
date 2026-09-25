"""Domain error base class. Deliberately free of DRF imports so models/services can use it."""

from typing import Any

from common.error_codes import ErrorCode


class DomainError(Exception):
    """Raise from services for expected business failures. Subclass per error family."""

    status_code: int = 400
    code: str = ErrorCode.VALIDATION_ERROR
    default_message: str = "The request could not be completed."
    headers: dict[str, str] | None = None  # extra response headers (e.g. Retry-After)

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message or self.default_message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class InvalidFields(DomainError):
    """Field-level validation failure raised by services: ``{"fields": {name: [messages]}}``."""

    status_code = 400
    code = ErrorCode.VALIDATION_ERROR
    default_message = "Some fields need attention."

    def __init__(self, fields: dict[str, list[str]], message: str | None = None) -> None:
        super().__init__(message, details={"fields": fields})


class NotFound(DomainError):
    """A record the caller asked for does not exist in their tenant (also for other tenants'
    records: never reveal that they exist)."""

    status_code = 404
    code = ErrorCode.NOT_FOUND
    default_message = "We couldn't find what you were looking for."
