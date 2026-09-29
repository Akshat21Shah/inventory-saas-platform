"""Compliance settings APIs (ADR-049 items 1, 3, 7): GST provider credentials (only with a module
on; masked, encrypted, checked in the background; owner only; per tenant), compliance settings
hidden while the modules are off, and the super admin's turnover band with its suggestions."""

import json
from typing import Any
from uuid import uuid4

import pytest
from django.db import connection

from apps.accounts.tests.factories import make_staff_in, make_super_admin
from apps.audit.models import AuditLog
from apps.compliance.models import GstCredential
from apps.compliance.tests.conftest import switch_on
from apps.orders.tests.helpers import client_for
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"
CREDS = f"{API}/settings/gst-credentials/"
GOOD: dict[str, Any] = {
    "environment": "SANDBOX",
    "values": {"username": "sharma_api", "password": "s3cret-pass"},
}


@pytest.fixture
def world(tenant_a, tenant_b, api_client_for, django_capture_on_commit_callbacks):
    owner = make_staff_in(tenant_a, "OWNER")
    return {
        "t": tenant_a,
        "owner": client_for(tenant_a, owner),
        "manager": client_for(tenant_a, make_staff_in(tenant_a, "MANAGER")),
        "sales": client_for(tenant_a, make_staff_in(tenant_a, "SALES")),
        "other": client_for(tenant_b, make_staff_in(tenant_b, "OWNER")),
        "tb": tenant_b,
        "admin": api_client_for(make_super_admin()),
        "run": lambda: django_capture_on_commit_callbacks(execute=True),
    }


def error_code(response: Any) -> str:
    return str(response.json()["error"]["code"])


@covers("gst-credentials", "gst-credentials-verify")
def test_credentials_need_a_compliance_module(world):
    for call in (
        world["owner"].get(CREDS),
        world["owner"].put(CREDS, GOOD, format="json"),
        world["owner"].post(f"{CREDS}verify/"),
    ):
        assert call.status_code == 403
        assert error_code(call) == "MODULE_NOT_ENABLED"
    with tenant_context(world["t"].pk):
        assert not GstCredential.objects.exists()


def test_the_owner_saves_and_checks_credentials(world):
    switch_on(world["t"], "einvoice")
    empty = world["owner"].get(CREDS).json()
    assert (empty["status"], empty["gstin"], empty["provider"]) == (
        "UNVERIFIED",
        world["t"].gstin,
        "mock",
    )
    assert empty["required_fields"] == ["username", "password"]
    with world["run"]():
        saved = world["owner"].put(CREDS, GOOD, format="json")
    assert saved.status_code == 200
    assert saved.json()["status"] == "CHECKING"  # the check runs after the save commits
    shown = world["owner"].get(CREDS).json()
    assert shown["status"] == "VERIFIED" and shown["verified_at"]
    assert shown["saved"]["password"] == "••••pass"  # never the secret itself
    assert "s3cret" not in json.dumps(shown)
    with connection.cursor() as cursor:
        cursor.execute("SELECT credentials FROM compliance_gstcredential")
        [(raw,)] = cursor.fetchall()
    assert "s3cret" not in raw  # encrypted at rest

    # A blank field keeps the saved value; a wrong password fails the check with the reason.
    with world["run"]():
        world["owner"].put(
            CREDS,
            {"environment": "SANDBOX", "values": {"username": "", "password": "wrong"}},
            format="json",
        )
    failed = world["owner"].get(CREDS).json()
    assert (failed["status"], failed["verified_at"]) == ("FAILED", None)
    assert failed["last_error"] == "The provider refused these credentials."
    assert failed["saved"]["username"] == "••••_api"
    with world["run"]():
        world["owner"].put(CREDS, GOOD, format="json")
        checked = world["owner"].post(f"{CREDS}verify/")
    assert checked.json()["status"] == "CHECKING"
    assert world["owner"].get(CREDS).json()["status"] == "VERIFIED"

    saves = AuditLog.objects.filter(action="compliance.credentials_saved").order_by("created_at")
    assert [entry.metadata["changed"] for entry in saves] == [
        ["password", "username"],
        ["password"],
        ["password"],
    ]
    assert "s3cret" not in json.dumps([entry.metadata for entry in saves])
    assert AuditLog.objects.filter(action="compliance.credentials_checked").count() == 4


def test_credentials_are_checked_on_save(world):
    switch_on(world["t"], "ewaybill")  # either module
    missing = world["owner"].put(
        CREDS, {"environment": "SANDBOX", "values": {"username": "u"}}, format="json"
    )
    assert missing.json()["error"]["details"]["fields"] == {"password": ["This field is required."]}
    unknown = world["owner"].put(
        CREDS, {"environment": "SANDBOX", "values": {**GOOD["values"], "pin": "1"}}, format="json"
    )
    assert unknown.json()["error"]["details"]["fields"] == {
        "pin": ["Not a field of this provider."]
    }
    assert world["owner"].post(f"{CREDS}verify/").status_code == 409  # nothing saved yet


def test_only_settings_managers_see_credentials_and_each_business_its_own(world):
    switch_on(world["t"], "einvoice")
    switch_on(world["tb"], "einvoice")
    with world["run"]():
        world["owner"].put(CREDS, GOOD, format="json")
    assert world["sales"].get(CREDS).status_code == 403
    assert world["manager"].get(CREDS).status_code == 403  # settings.manage is the owner's
    theirs = world["other"].get(CREDS).json()
    assert (theirs["status"], theirs["saved"]["password"]) == ("UNVERIFIED", "")
    assert theirs["gstin"] == world["tb"].gstin


def test_compliance_settings_show_only_with_their_module(world):
    def keys() -> set[str]:
        rows = world["owner"].get(f"{API}/settings/registry/").json()
        return {row["key"] for row in rows}

    assert not {"compliance.turnover_band", "einvoice.auto_generate"} & keys()
    refused = world["owner"].patch(
        f"{API}/settings/values/",
        {"values": {"compliance.turnover_band": "FROM_10_CR"}},
        format="json",
    )
    assert (refused.status_code, error_code(refused)) == (403, "MODULE_NOT_ENABLED")
    switch_on(world["t"], "ewaybill")
    assert "compliance.turnover_band" in keys() and "einvoice.auto_generate" not in keys()
    switch_on(world["t"], "einvoice")
    assert {"compliance.turnover_band", "einvoice.auto_generate"} <= keys()
    changed = world["owner"].patch(
        f"{API}/settings/values/",
        {"values": {"compliance.turnover_band": "FROM_10_CR"}},
        format="json",
    )
    assert changed.status_code == 200


@covers("platform-tenant-turnover")
def test_the_super_admin_sets_the_turnover_band(world):
    url = f"{API}/platform/tenants/{world['t'].pk}/turnover-band/"
    shown = world["admin"].get(url).json()
    assert shown == {
        "turnover_band": "BELOW_5_CR",
        "einvoice_suggested": False,
        "reporting_limit_applies": False,
        "reporting_days": 30,
        "einvoice_enabled": False,
        "ewaybill_enabled": False,
    }
    middle = world["admin"].put(url, {"turnover_band": "FROM_5_TO_10_CR"}, format="json").json()
    assert (middle["einvoice_suggested"], middle["reporting_limit_applies"]) == (True, False)
    top = world["admin"].put(url, {"turnover_band": "FROM_10_CR"}, format="json").json()
    assert (top["einvoice_suggested"], top["reporting_limit_applies"]) == (True, True)
    entry = AuditLog.objects.filter(action="settings.changed", tenant_id=world["t"].pk).latest(
        "created_at"
    )
    assert entry.changes["value"] == ["FROM_5_TO_10_CR", "FROM_10_CR"]
    assert entry.actor_type == "PLATFORM"
    bad = world["admin"].put(url, {"turnover_band": "HUGE"}, format="json")
    assert bad.status_code == 400
    missing = world["admin"].get(f"{API}/platform/tenants/{uuid4()}/turnover-band/")
    assert missing.status_code == 404
    assert world["owner"].get(url).status_code == 403
