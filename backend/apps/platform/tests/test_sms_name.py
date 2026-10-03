"""A short name for SMS (owner, 11a final review): the owner sets it on the business details
(audited); SMS use it in place of the business name, the sign-in code SMS too; a live preview shows
the welcome SMS in each of the distributor's languages with its length and parts. The link is
never shortened: a text over one part goes as two, and the preview says so."""

from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.adapters.sms import MockSmsSender
from apps.accounts.tests.factories import make_staff_in
from apps.accounts.tokens import issue_tokens
from apps.audit.models import AuditLog
from apps.notifications import sms_length
from apps.retailers.models import Retailer
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"
BUSINESS = f"{API}/settings/business/"
PREVIEW = f"{API}/settings/business/sms-preview/"


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    MockSmsSender.outbox.clear()
    yield
    cache.clear()
    MockSmsSender.outbox.clear()


def _client(tenant: Any, role: str = "OWNER") -> APIClient:
    client = APIClient()
    user = make_staff_in(tenant, role)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, tenant.pk).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant.slug}.localhost"
    return client


def test_the_owner_sets_it_and_it_is_audited(tenant_a):
    owner = _client(tenant_a)
    saved = owner.patch(BUSINESS, {"sms_name": "  Sharma Traders  "}, format="json")
    assert saved.status_code == 200, saved.json()
    assert saved.json()["sms_name"] == "Sharma Traders"
    log = AuditLog.objects.get(action="settings.business_profile_changed")
    assert log.changes["sms_name"] == ["", "Sharma Traders"]
    two_lines = owner.patch(BUSINESS, {"sms_name": "Sharma\nTraders"}, format="json")
    assert "sms_name" in two_lines.json()["error"]["details"]["fields"]
    too_long = owner.patch(BUSINESS, {"sms_name": "S" * 31}, format="json")
    assert "sms_name" in too_long.json()["error"]["details"]["fields"]
    manager = _client(tenant_a, "MANAGER")  # the owner's: settings.manage
    assert manager.patch(BUSINESS, {"sms_name": "X"}, format="json").status_code == 403


@covers("settings-business-sms-preview")
def test_the_preview_shows_each_language_with_its_length_and_parts(
    tenant_a, tenant_b, every_language
):
    owner = _client(tenant_a)
    rows = {row["language"]: row for row in owner.get(PREVIEW, {"name": "Sharma"}).json()}
    assert set(rows) == {"en", "hi", "mr"}
    hindi = rows["hi"]
    assert hindi["text"].startswith("Sharma: ") and hindi["text"].endswith("/shop/login")
    assert f"{tenant_a.slug}." in hindi["text"]  # the distributor's own sign-in link, whole
    assert (hindi["length"], hindi["single"], hindi["parts"]) == (
        sms_length.length(hindi["text"]),
        70,
        1,
    )
    assert rows["en"]["single"] == 160
    # A long name: the link stays whole, the text goes in two parts.
    long_name = "Shree Mahalaxmi Distributors"
    long = {r["language"]: r for r in owner.get(PREVIEW, {"name": long_name}).json()}
    assert long["hi"]["parts"] == 2 and long["hi"]["text"].endswith("/shop/login")
    # Blank: the business name. Another distributor sees its own name and link.
    blank = owner.get(PREVIEW).json()
    assert all(row["text"].startswith(tenant_a.name) for row in blank if row["language"] != "en")
    other = _client(tenant_b).get(PREVIEW, {"name": "B"}).json()
    assert all(tenant_b.slug in row["text"] for row in other)
    assert all(tenant_a.slug not in row["text"] for row in other)
    assert owner.get(PREVIEW, {"name": "a\nb"}).status_code == 400


def test_sms_use_the_short_name_the_sign_in_code_too(
    tenant_a, every_language, django_capture_on_commit_callbacks
):
    owner = _client(tenant_a)
    owner.patch(BUSINESS, {"sms_name": "Sharma"}, format="json")
    with django_capture_on_commit_callbacks(execute=True):
        created = owner.post(
            f"{API}/retailers/",
            {"shop_name": "Ganesh Kirana", "mobile": "98765 43210", "owner_name": "Ganesh"},
            format="json",
        )
    assert created.status_code == 201, created.json()
    [welcome] = MockSmsSender.outbox
    assert welcome.text.startswith("Sharma: ") and welcome.sender_name == "Sharma"
    with tenant_context(tenant_a.pk):
        Retailer.objects.update(preferred_language="hi")
    MockSmsSender.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        sent = APIClient().post(
            f"{API}/auth/retailer/otp/request/",
            {"phone": "9876543210"},
            format="json",
            HTTP_X_FORWARDED_HOST=f"{tenant_a.slug}.localhost",
        )
    assert sent.status_code in (200, 202), sent.json()
    assert MockSmsSender.outbox[-1].sender_name == "Sharma"
