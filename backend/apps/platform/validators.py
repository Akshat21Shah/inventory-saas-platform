"""Validators for Indian business identifiers and platform values.

These run in serializers and model validation; the most important invariants are also enforced by
database check constraints on the models.
"""

import re

from django.core.exceptions import ValidationError

from common.hosts import RESERVED_TENANT_SLUGS, SLUG_RE

# Regular taxpayer GSTIN: state code (2) + PAN (10) + entity number (1) + "Z" + check character.
# TODO(verify): other registration kinds (TDS/TCS deductors, UN bodies, NRTP) use other layouts.
# Only REGULAR is supported in v1 (ADR-012); check the GSTN format spec before adding them.
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
PINCODE_RE = re.compile(r"^[1-9][0-9]{5}$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
HEX_COLOR_RE = re.compile(r"^#[0-9a-f]{6}$")
HSN_PREFIX_RE = re.compile(r"^[0-9]{2,8}$")
BUSINESS_PHONE_RE = re.compile(r"^\+?[0-9]{10,15}$")
UPI_RE = re.compile(r"^[A-Za-z0-9._-]{2,256}@[A-Za-z][A-Za-z0-9]{1,64}$")

_GSTIN_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_char(first14: str) -> str:
    """Check character of a GSTIN (mod-36 weighted sum over the first 14 characters)."""
    total = 0
    for index, char in enumerate(first14):
        product = _GSTIN_ALPHABET.index(char) * (1 if index % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _GSTIN_ALPHABET[(36 - total % 36) % 36]


def validate_gstin(value: str) -> None:
    if not GSTIN_RE.match(value or ""):
        raise ValidationError("Enter a valid 15-character GSTIN.", code="invalid_gstin")
    if gstin_check_char(value[:14]) != value[14]:
        raise ValidationError("This GSTIN's check character is wrong.", code="invalid_gstin")


def validate_pan(value: str) -> None:
    if not PAN_RE.match(value or ""):
        raise ValidationError("Enter a valid 10-character PAN.", code="invalid_pan")


def validate_pincode(value: str) -> None:
    if not PINCODE_RE.match(value or ""):
        raise ValidationError("Enter a valid 6-digit PIN code.", code="invalid_pincode")


def validate_ifsc(value: str) -> None:
    if not IFSC_RE.match(value or ""):
        raise ValidationError("Enter a valid 11-character IFSC code.", code="invalid_ifsc")


def validate_hex_color(value: str) -> None:
    if not HEX_COLOR_RE.match(value or ""):
        raise ValidationError("Enter a colour like #1a73e8.", code="invalid_color")


def validate_hsn_prefix(value: str) -> None:
    if not HSN_PREFIX_RE.match(value or ""):
        raise ValidationError("Enter 2 to 8 digits of an HSN code.", code="invalid_hsn")


def validate_business_phone(value: str) -> None:
    if not BUSINESS_PHONE_RE.match(value or ""):
        raise ValidationError("Enter a phone number with 10 to 15 digits.", code="invalid_phone")


def validate_upi_id(value: str) -> None:
    if not UPI_RE.match(value or ""):
        raise ValidationError("Enter a UPI ID like shopname@bank.", code="invalid_upi")


def validate_tenant_slug(value: str) -> None:
    if not SLUG_RE.match(value or ""):
        raise ValidationError(
            "Use 3 to 30 lowercase letters, numbers or hyphens, starting and ending with a letter "
            "or number.",
            code="invalid_slug",
        )
    if value in RESERVED_TENANT_SLUGS:
        raise ValidationError("This address is reserved. Choose another.", code="reserved_slug")
