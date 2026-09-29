"""The mock GST provider behaves like a portal (ADR-049 item 4): IRNs, duplicates in any letter
case, an inactive buyer GSTIN, the document's problems, the portal down, timeouts (including a
lost answer), cancelling within the window and only once, credentials, and no mock outside dev."""

from datetime import datetime, timedelta
from typing import Any

import pytest
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured

from apps.compliance.adapters import get_gsp_client
from apps.compliance.adapters.base import GspCredentials, GspError, GspErrorCode
from apps.compliance.adapters.mock import MockGspClient, _key

pytestmark = pytest.mark.django_db
CREDS = GspCredentials("mock", "SANDBOX", "27AAACT0001F1Z5", {"username": "u", "password": "p"})


def document(number: str = "INV/26-27/000001", **changes: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "document": {
            "type": "INVOICE",
            "number": number,
            "number_key": number.upper(),
            "date": "2026-09-29",
            "financial_year": "2026-27",
        },
        "seller": {"gstin": "27AAACT0001F1Z5", "pincode": "411001"},
        "buyer": {"gstin": "29AAACT0002F1ZA", "pincode": "560001"},
        "lines": [
            {"line_no": 1, "hsn_code": "8471", "taxable_value": "60000.00"},
            {"line_no": 2, "hsn_code": "1905", "taxable_value": "500.00"},
        ],
        "totals": {"taxable_value": "60500.00", "grand_total": "71390.00"},
    }
    for path, value in changes.items():
        part, key = path.split("__")
        doc[part][key] = value
    return doc


def fails(code: str, doc: dict[str, Any] | None = None) -> GspError:
    with pytest.raises(GspError) as caught:
        MockGspClient().generate_irn(doc or document(), CREDS)
    assert caught.value.code == code
    return caught.value


def test_an_irn_is_stable_and_printable():
    result = MockGspClient().generate_irn(document(), CREDS)
    assert len(result.irn) == 64 and int(result.irn, 16) >= 0
    assert len(result.ack_no) == 15 and result.ack_no.isdigit()
    assert result.signed_qr.startswith("MOCK.") and result.signed_qr.endswith(".MOCK")
    assert result.irn == MockGspClient.irn_of(document())


def test_the_same_number_in_another_letter_case_is_a_duplicate():
    first = MockGspClient().generate_irn(document("INV/26-27/000001"), CREDS)
    duplicate = fails(GspErrorCode.DUPLICATE, document("inv/26-27/000001"))
    assert duplicate.details == {"irn": first.irn, "cancelled": False}
    assert not duplicate.retryable
    found = MockGspClient().irn_for_document(document("inv/26-27/000001"), CREDS)
    assert found is not None and found.irn == first.irn


def test_an_inactive_buyer_gstin_and_the_documents_problems_are_refused():
    inactive = fails(GspErrorCode.INVALID_GSTIN, document(buyer__gstin="29ZZZZZ9999Z1Z5"))
    assert not inactive.retryable
    problems = fails(
        GspErrorCode.VALIDATION, document(buyer__gstin="", buyer__pincode="5600")
    ).details["problems"]
    assert problems == [
        "The buyer's GSTIN is required for a B2B document.",
        "The buyer's PIN code must have 6 digits.",
    ]
    short_hsn = document()
    short_hsn["lines"][1]["hsn_code"] = "190"
    short_hsn["totals"]["taxable_value"] = "60499.00"
    assert fails(GspErrorCode.VALIDATION, short_hsn).details["problems"] == [
        "Line 2: the HSN code needs at least 4 digits.",
        "The lines' taxable values don't add up to the total.",
    ]
    assert MockGspClient().irn_for_document(document(), CREDS) is None  # nothing registered


def test_the_portal_down_and_timeouts_can_be_retried():
    MockGspClient.script("PORTAL_DOWN", "TIMEOUT")
    assert fails(GspErrorCode.PORTAL_DOWN).retryable
    assert fails(GspErrorCode.TIMEOUT).retryable
    assert MockGspClient().generate_irn(document(), CREDS).irn


def test_a_lost_answer_leaves_the_irn_registered():
    MockGspClient.script("TIMEOUT_AFTER_SAVE")
    fails(GspErrorCode.TIMEOUT)
    assert fails(GspErrorCode.DUPLICATE).details["cancelled"] is False
    assert MockGspClient().irn_for_document(document(), CREDS) is not None


def test_scripts_are_checked():
    with pytest.raises(ValueError, match="EXPLODE"):
        MockGspClient.script("EXPLODE")


def test_cancelling_works_once_within_the_window():
    client = MockGspClient()
    irn = client.generate_irn(document(), CREDS).irn
    assert client.cancel_irn(irn, "2", "Wrong rate", CREDS).cancelled_at
    with pytest.raises(GspError) as again:
        client.cancel_irn(irn, "2", "Wrong rate", CREDS)
    assert again.value.code == GspErrorCode.CANCEL_NOT_ALLOWED
    assert client.irn_for_document(document(), CREDS) is None
    assert fails(GspErrorCode.DUPLICATE).details["cancelled"] is True  # the number is used up

    late = client.generate_irn(document("INV/26-27/000002"), CREDS).irn
    stored = cache.get(_key(late))
    old = datetime.fromisoformat(stored["ack_date"]) - timedelta(hours=25)
    cache.set(_key(late), {**stored, "ack_date": old.isoformat()}, None)
    with pytest.raises(GspError) as over:
        client.cancel_irn(late, "2", "Too late", CREDS)
    assert over.value.code == GspErrorCode.CANCEL_NOT_ALLOWED
    with pytest.raises(GspError) as missing:
        client.cancel_irn("0" * 64, "2", "", CREDS)
    assert missing.value.code == GspErrorCode.NOT_FOUND


def test_credentials_are_checked_on_every_call():
    wrong = GspCredentials("mock", "SANDBOX", CREDS.gstin, {"username": "u", "password": "wrong"})
    with pytest.raises(GspError) as caught:
        MockGspClient().generate_irn(document(), wrong)
    assert caught.value.code == GspErrorCode.AUTH_FAILED
    with pytest.raises(GspError):
        MockGspClient().verify(GspCredentials("mock", "SANDBOX", CREDS.gstin, {}))
    MockGspClient().verify(CREDS)


def test_the_mock_is_refused_outside_dev_and_test(settings):
    assert isinstance(get_gsp_client("mock"), MockGspClient)
    settings.ALLOW_MOCK_INTEGRATIONS = False
    with pytest.raises(ImproperlyConfigured):
        get_gsp_client("mock")
    with pytest.raises(ImproperlyConfigured):
        get_gsp_client("some-gsp")


def test_the_deploy_check_refuses_the_mock(settings):
    from apps.compliance.checks import gsp_provider_check

    assert gsp_provider_check(None) == []
    settings.ALLOW_MOCK_INTEGRATIONS = False
    assert [e.id for e in gsp_provider_check(None)] == ["compliance.E001"]


def test_dev_can_script_the_mock_from_the_command_line(settings):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    call_command("mock_gsp", "portal_down")
    assert fails(GspErrorCode.PORTAL_DOWN).retryable
    with pytest.raises(CommandError):
        call_command("mock_gsp", "explode")
    MockGspClient().generate_irn(document(), CREDS)
    call_command("mock_gsp", "--reset")
    assert MockGspClient().irn_for_document(document(), CREDS) is None
    settings.ALLOW_MOCK_INTEGRATIONS = False
    with pytest.raises(CommandError):
        call_command("mock_gsp", "timeout")
