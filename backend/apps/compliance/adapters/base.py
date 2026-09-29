"""The GST provider (GSP) adapter interface (ADR-049 item 4).

We hand the adapter our own neutral document (``apps.compliance.document``) and get back neutral
results. Turning the document into the provider's request, and its answers into these results,
is the real adapter's job, written against the chosen provider's official documentation.

TODO(verify): no GSP is chosen yet (PROGRESS pre-production item 18). Before production: its
authentication and token lifetime, request and response field names, error codes and which of
them are worth retrying, rate limits, and its sandbox. Only the mock exists; deployed environments
refuse it (``compliance.E001``).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


class GspErrorCode:
    """Our neutral error codes. A real adapter maps the provider's codes onto these."""

    AUTH_FAILED = "AUTH_FAILED"  # wrong or expired credentials: fix them, then retry
    INVALID_GSTIN = "INVALID_GSTIN"  # the buyer's GSTIN isn't valid or active on the portal
    VALIDATION = "VALIDATION"  # the portal refused the document's contents
    DUPLICATE = "DUPLICATE"  # an IRN already exists for this document number
    PORTAL_DOWN = "PORTAL_DOWN"  # the portal or provider is unavailable: try again later
    TIMEOUT = "TIMEOUT"  # no answer in time: the IRN may or may not exist; try again
    CANCEL_NOT_ALLOWED = "CANCEL_NOT_ALLOWED"  # outside the window
    ALREADY_CANCELLED = "ALREADY_CANCELLED"  # e.g. our first request's answer was lost
    NOT_FOUND = "NOT_FOUND"


RETRYABLE = frozenset({GspErrorCode.PORTAL_DOWN, GspErrorCode.TIMEOUT})


class GspError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.raw = raw or {}

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE


@dataclass(frozen=True)
class GspCredentials:
    """The distributor's login with the provider; ``values`` holds the provider's own fields."""

    provider: str
    environment: str
    gstin: str
    values: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class IrnResult:
    irn: str
    ack_no: str
    ack_date: datetime
    signed_invoice: str
    signed_qr: str  # printed as a QR code exactly as returned
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CancelResult:
    cancelled_at: datetime
    raw: dict[str, Any] = field(default_factory=dict)


class GspClient(Protocol):
    def verify(self, credentials: GspCredentials) -> None:
        """Sign in with the credentials; raises GspError(AUTH_FAILED) when they don't work."""

    def generate_irn(self, document: dict[str, Any], credentials: GspCredentials) -> IrnResult:
        """Register an invoice or credit note. Raises GspError; a DUPLICATE error carries the
        existing IRN's details in ``details`` when the provider returns them."""

    def irn_for_document(
        self, document: dict[str, Any], credentials: GspCredentials
    ) -> IrnResult | None:
        """The IRN already registered for this document number, if any (after a DUPLICATE
        or a TIMEOUT)."""

    def cancel_irn(
        self, irn: str, reason_code: str, remarks: str, credentials: GspCredentials
    ) -> CancelResult:
        """Cancel an IRN within the permitted window."""
