import pytest
from django.core.exceptions import ValidationError

from apps.platform import validators as v
from apps.platform.tests.factories import make_gstin


@pytest.mark.parametrize(
    "gstin", ["27AAPFU0939F1ZV", "24AAACC1206D1ZM", make_gstin(1), make_gstin(9999, "07")]
)
def test_valid_gstins(gstin):
    v.validate_gstin(gstin)


@pytest.mark.parametrize(
    "gstin",
    [
        "27AAPFU0939F1ZW",  # wrong check character
        "27aapfu0939f1zv",  # lowercase
        "27AAPFU0939F1Z",  # too short
        "27AAPFU0939F0ZV",  # entity number 0
        "27AAPFU0939F1XV",  # 14th character must be Z
        "",
    ],
)
def test_invalid_gstins(gstin):
    with pytest.raises(ValidationError):
        v.validate_gstin(gstin)


def test_check_char_detects_single_character_change():
    base = "27AAPFU0939F1Z"
    assert v.gstin_check_char(base) == "V"
    assert v.gstin_check_char("27AAPFU0939F2Z") != "V"


@pytest.mark.parametrize(
    ("validator", "good", "bad"),
    [
        (v.validate_pan, "AAPFU0939F", "AAPF0939FU"),
        (v.validate_pincode, "411001", "011001"),
        (v.validate_ifsc, "HDFC0001234", "HDFC1001234"),
        (v.validate_hex_color, "#2f5bea", "#2F5BEA"),
        (v.validate_hsn_prefix, "3004", "3"),
        (v.validate_business_phone, "+912024451234", "12345"),
        (v.validate_upi_id, "sharma.traders@okhdfc", "sharma"),
    ],
)
def test_simple_validators(validator, good, bad):
    validator(good)
    with pytest.raises(ValidationError):
        validator(bad)


@pytest.mark.parametrize("slug", ["abc", "sharma-traders", "a1b", "x" * 30])
def test_valid_slugs(slug):
    v.validate_tenant_slug(slug)


@pytest.mark.parametrize(
    ("slug", "code"),
    [
        ("ab", "invalid_slug"),
        ("-abc", "invalid_slug"),
        ("abc-", "invalid_slug"),
        ("Sharma", "invalid_slug"),
        ("x" * 31, "invalid_slug"),
        ("admin", "reserved_slug"),
        ("platform", "reserved_slug"),
        ("shop", "reserved_slug"),
    ],
)
def test_invalid_slugs(slug, code):
    with pytest.raises(ValidationError) as exc:
        v.validate_tenant_slug(slug)
    assert exc.value.code == code
