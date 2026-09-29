"""A mock GST provider for dev and tests (ADR-049 item 4). It behaves like a portal, predictably:

- Credentials: any username and password work, except the password ``wrong`` (AUTH_FAILED).
- A buyer GSTIN whose PAN part is ``ZZZZZ9999Z`` is "not active on the portal" (INVALID_GSTIN).
- The document is checked: a buyer GSTIN (B2B only), HSN codes of at least 4 digits, 6-digit PIN
  codes, and line taxable values adding up to the total (VALIDATION, with every problem).
- The same seller, document type, number (in any letter case) and year twice: DUPLICATE, with the
  IRN already registered; a cancelled IRN's number can't be used again.
- Cancelling works once, within ``platform.irn_cancel_window_hours`` of the acknowledgement.
- Outcomes can be scripted for the next calls, shared through the cache so a dev worker sees them
  too (``manage.py mock_gsp portal_down timeout``): PORTAL_DOWN, TIMEOUT, and
  TIMEOUT_AFTER_SAVE (the IRN is registered but the answer is lost, as on a real network).

IRNs are the SHA-256 of the document's identity, like the portal's, so they are stable. The signed
QR is a readable stand-in (``MOCK.<base64 JSON>.MOCK``), never a real signature.
"""

import base64
import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.core.cache import cache
from django.utils import timezone

from apps.compliance.adapters.base import (
    CancelResult,
    GspCredentials,
    GspError,
    GspErrorCode,
    IrnResult,
)

INACTIVE_PAN = "ZZZZZ9999Z"
SCRIPT_KEY = "mockgsp:script"
SCRIPTABLE = ("PORTAL_DOWN", "TIMEOUT", "TIMEOUT_AFTER_SAVE")
_TTL = None  # kept until the cache is cleared


def _key(irn: str) -> str:
    return f"mockgsp:irn:{irn}"


def _b64(data: dict[str, Any]) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class MockGspClient:
    @staticmethod
    def script(*outcomes: str) -> None:
        """Queue outcomes for the next calls (tests, and ``manage.py mock_gsp`` in dev)."""
        unknown = [o for o in outcomes if o not in SCRIPTABLE]
        if unknown:
            raise ValueError(f"Unknown mock GSP outcome(s): {', '.join(unknown)}")
        cache.set(SCRIPT_KEY, [*(cache.get(SCRIPT_KEY) or []), *outcomes], _TTL)

    @staticmethod
    def reset() -> None:
        cache.delete(SCRIPT_KEY)
        cache.delete_many(list(cache.get("mockgsp:irns") or []))
        cache.delete("mockgsp:irns")

    @staticmethod
    def _next() -> str | None:
        queue = cache.get(SCRIPT_KEY) or []
        if not queue:
            return None
        cache.set(SCRIPT_KEY, queue[1:], _TTL)
        return str(queue[0])

    # --- Sign-in ---------------------------------------------------------------------------

    def verify(self, credentials: GspCredentials) -> None:
        values = credentials.values
        if not values.get("username") or not values.get("password"):
            raise GspError(GspErrorCode.AUTH_FAILED, "Enter the username and password.")
        if values.get("password") == "wrong":
            raise GspError(GspErrorCode.AUTH_FAILED, "The provider refused these credentials.")

    # --- IRN -------------------------------------------------------------------------------

    @staticmethod
    def irn_of(document: dict[str, Any]) -> str:
        identity = "".join(
            (
                document["seller"]["gstin"],
                document["document"]["financial_year"],
                document["document"]["type"],
                document["document"]["number"].strip().upper(),
            )
        )
        return hashlib.sha256(identity.encode()).hexdigest()

    @staticmethod
    def _problems(document: dict[str, Any]) -> list[str]:
        problems = []
        buyer = document["buyer"]
        if not buyer.get("gstin"):
            problems.append("The buyer's GSTIN is required for a B2B document.")
        for party in ("seller", "buyer"):
            pincode = str(document[party].get("pincode", ""))
            if len(pincode) != 6 or not pincode.isdigit():
                problems.append(f"The {party}'s PIN code must have 6 digits.")
        for line in document["lines"]:
            if len(line["hsn_code"]) < 4:
                problems.append(f"Line {line['line_no']}: the HSN code needs at least 4 digits.")
        taxable = sum(Decimal(line["taxable_value"]) for line in document["lines"])
        if taxable != Decimal(document["totals"]["taxable_value"]):
            problems.append("The lines' taxable values don't add up to the total.")
        return problems

    def _result(self, irn: str, stored: dict[str, Any]) -> IrnResult:
        return IrnResult(
            irn=irn,
            ack_no=stored["ack_no"],
            ack_date=datetime.fromisoformat(stored["ack_date"]),
            signed_invoice=stored["signed_invoice"],
            signed_qr=stored["signed_qr"],
            raw={"mock": True, "irn": irn, "ack_no": stored["ack_no"]},
        )

    def _register(self, document: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        irn, now = self.irn_of(document), timezone.now()
        doc, lines = document["document"], document["lines"]
        qr = {
            "seller_gstin": document["seller"]["gstin"],
            "buyer_gstin": document["buyer"]["gstin"],
            "document_number": doc["number"],
            "document_type": doc["type"],
            "document_date": doc["date"],
            "total": document["totals"]["grand_total"],
            "item_count": len(lines),
            "main_hsn": lines[0]["hsn_code"] if lines else "",
            "irn": irn,
            "irn_date": now.isoformat(),
        }
        stored = {
            "ack_no": f"{int(irn[:13], 16) % 10**15:015d}",
            "ack_date": now.isoformat(),
            "signed_qr": f"MOCK.{_b64(qr)}.MOCK",
            "signed_invoice": f"MOCK.{_b64({'irn': irn, 'document': doc})}.MOCK",
            "cancelled": False,
        }
        cache.set(_key(irn), stored, _TTL)
        cache.set("mockgsp:irns", [*(cache.get("mockgsp:irns") or []), _key(irn)], _TTL)
        return irn, stored

    def generate_irn(self, document: dict[str, Any], credentials: GspCredentials) -> IrnResult:
        self.verify(credentials)
        scripted = self._next()
        if scripted == "PORTAL_DOWN":
            raise GspError(GspErrorCode.PORTAL_DOWN, "The e-invoice portal is not available.")
        if scripted == "TIMEOUT":
            raise GspError(GspErrorCode.TIMEOUT, "The provider didn't answer in time.")
        if document["buyer"].get("gstin", "")[2:12] == INACTIVE_PAN:
            raise GspError(
                GspErrorCode.INVALID_GSTIN,
                "The buyer's GSTIN is not active on the portal.",
                details={"gstin": document["buyer"]["gstin"]},
            )
        problems = self._problems(document)
        if problems:
            raise GspError(
                GspErrorCode.VALIDATION, "; ".join(problems), details={"problems": problems}
            )
        irn = self.irn_of(document)
        existing = cache.get(_key(irn))
        if existing is not None:
            raise GspError(
                GspErrorCode.DUPLICATE,
                "An IRN already exists for this document number.",
                details={"irn": irn, "cancelled": existing["cancelled"]},
            )
        irn, stored = self._register(document)
        if scripted == "TIMEOUT_AFTER_SAVE":
            raise GspError(GspErrorCode.TIMEOUT, "The provider didn't answer in time.")
        return self._result(irn, stored)

    def irn_for_document(
        self, document: dict[str, Any], credentials: GspCredentials
    ) -> IrnResult | None:
        self.verify(credentials)
        irn = self.irn_of(document)
        stored = cache.get(_key(irn))
        if stored is None or stored["cancelled"]:
            return None
        return self._result(irn, stored)

    def cancel_irn(
        self, irn: str, reason_code: str, remarks: str, credentials: GspCredentials
    ) -> CancelResult:
        from apps.platform.selectors import get_platform_setting

        self.verify(credentials)
        if self._next() == "PORTAL_DOWN":
            raise GspError(GspErrorCode.PORTAL_DOWN, "The e-invoice portal is not available.")
        stored = cache.get(_key(irn))
        if stored is None:
            raise GspError(GspErrorCode.NOT_FOUND, "No such IRN.")
        if stored["cancelled"]:
            raise GspError(GspErrorCode.CANCEL_NOT_ALLOWED, "This IRN is already cancelled.")
        hours = int(get_platform_setting("platform.irn_cancel_window_hours"))
        if timezone.now() > datetime.fromisoformat(stored["ack_date"]) + timedelta(hours=hours):
            raise GspError(
                GspErrorCode.CANCEL_NOT_ALLOWED, "The time allowed for cancelling has passed."
            )
        now = timezone.now()
        cache.set(_key(irn), {**stored, "cancelled": True, "cancelled_at": now.isoformat()}, _TTL)
        return CancelResult(cancelled_at=now, raw={"mock": True, "irn": irn})
