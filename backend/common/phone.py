"""Indian mobile numbers, stored in E.164 form (+91XXXXXXXXXX)."""

import re

from django.core.exceptions import ValidationError

_MOBILE_RE = re.compile(r"^[6-9][0-9]{9}$")


def normalize_indian_mobile(raw: str) -> str:
    """Accepts "98765 43210", "+91 98765-43210", "09876543210", "919876543210" → "+919876543210"."""
    digits = re.sub(r"[\s\-().]", "", raw or "")
    if digits.startswith("+91"):
        digits = digits[3:]
    elif len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not _MOBILE_RE.match(digits):
        raise ValidationError("Enter a 10-digit mobile number.", code="invalid_mobile")
    return f"+91{digits}"
