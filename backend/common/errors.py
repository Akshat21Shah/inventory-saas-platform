"""Domain error base class. Deliberately free of DRF imports so models/services can use it."""

from typing import Any

from common.error_codes import ErrorCode


class DomainError(Exception):
    """Raise from services for expected business failures. Subclass per error family."""

    status_code: int = 400
    code: str = ErrorCode.VALIDATION_ERROR
    default_message: str = "The request could not be completed."

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
