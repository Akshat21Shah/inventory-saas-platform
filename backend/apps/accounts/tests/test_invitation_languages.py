"""The invitation's language (ADR-060, owner at the 11a checkpoint): the inviter chooses it when
sending, their own by default; the email and the invite page use it, and a new account keeps the
language its invite page was shown in. Only languages the distributor's people may use."""

import re
from typing import Any

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.accounts.models import Invitation, User
from apps.accounts.tests.factories import make_staff_in
from apps.accounts.tokens import issue_tokens
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def _client(user, tenant):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, tenant.pk).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant.slug}.localhost"
    return client


@pytest.fixture
def owner(tenant_a):
    return make_staff_in(tenant_a, "OWNER", email="owner-lang@example.com")


@pytest.fixture
def invite(owner, tenant_a, django_capture_on_commit_callbacks):
    def _invite(email: str, **extra):
        with django_capture_on_commit_callbacks(execute=True):
            return _client(owner, tenant_a).post(
                "/api/v1/staff/invitations/",
                {"email": email, "role_code": "SALES", **extra},
                format="json",
            )

    return _invite


def _token() -> str:
    match = re.search(r"/invite/([A-Za-z0-9_\-]+)", str(mail.outbox[-1].body))
    assert match, mail.outbox[-1].body
    return match.group(1)


def _public(path: str, data: dict[str, str], tenant: Any) -> dict[str, Any]:
    response = APIClient().post(
        path, data, format="json", HTTP_X_FORWARDED_HOST=f"{tenant.slug}.localhost"
    )
    body: dict[str, Any] = response.json()
    return body


def test_by_default_the_invitation_goes_in_the_inviters_language(
    tenant_a, owner, invite, every_language
):
    User.objects.filter(pk=owner.pk).update(preferred_language="mr")
    response = invite("marathi@example.com")
    assert response.status_code == 201, response.json()
    assert response.json()["language"] == "mr"
    email = mail.outbox[-1]
    assert DEVANAGARI.search(str(email.subject)) and DEVANAGARI.search(str(email.body))
    assert "Sales" not in email.body  # the role's name too


def test_the_inviter_chooses_and_the_new_account_keeps_it(tenant_a, invite, every_language):
    assert invite("hindi@example.com", language="hi").json()["language"] == "hi"
    assert DEVANAGARI.search(str(mail.outbox[-1].subject))
    token = _token()
    preview = _public("/api/v1/auth/invitations/preview/", {"token": token}, tenant_a)
    assert preview["language"] == "hi"  # the page opens in it
    accepted = _public(
        "/api/v1/auth/invitations/accept/",
        {"token": token, "full_name": "Ravi", "password": "a-new-strong-passphrase"},
        tenant_a,
    )
    assert accepted["status"] == "authenticated"
    assert User.objects.get(email="hindi@example.com").preferred_language == "hi"

    # Switched on the page before accepting: that one is kept.
    invite("switched@example.com", language="hi")
    _public(
        "/api/v1/auth/invitations/accept/",
        {
            "token": _token(),
            "full_name": "Meera",
            "password": "a-new-strong-passphrase",
            "language": "en",
        },
        tenant_a,
    )
    assert User.objects.get(email="switched@example.com").preferred_language == "en"


def test_only_a_language_the_distributors_people_may_use(tenant_a, invite):
    # Hindi and Marathi are off for real distributors until their review (ADR-060 item 12).
    refused = invite("early@example.com", language="hi")
    assert refused.status_code == 400
    assert "language" in refused.json()["error"]["details"]["fields"]
    assert invite("english@example.com").json()["language"] == "en"
    with tenant_context(tenant_a.pk):
        assert Invitation.objects.get(email="english@example.com").language == "en"
    assert not DEVANAGARI.search(str(mail.outbox[-1].subject))


def test_an_unknown_language_is_refused(invite, every_language):
    assert invite("x@example.com", language="kn").status_code == 400
