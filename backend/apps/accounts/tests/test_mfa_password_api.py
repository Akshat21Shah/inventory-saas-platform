"""Two-step verification and password flows (spec 5.2, ADR-030)."""

import re
import time

import pyotp
import pytest
from django.core import mail
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import LoginChallenge, RecoveryCode, User
from apps.accounts.tests.factories import (
    enable_totp,
    make_membership,
    make_staff_in,
    make_super_admin,
)
from apps.accounts.tokens import issue_tokens
from apps.audit.models import AuditLog
from apps.platform import services as platform_services
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db

PASSWORD = "a-strong-password"
LOGIN = "/api/v1/auth/staff/login/"


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


def _login(email, host, password=PASSWORD):
    return APIClient().post(
        LOGIN, {"email": email, "password": password}, format="json", HTTP_X_FORWARDED_HOST=host
    )


def _post(path, data, host, access=None):
    client = APIClient()
    if access:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client.post(path, data, format="json", HTTP_X_FORWARDED_HOST=host)


def _code(secret, offset_steps=0):
    return pyotp.TOTP(secret).at(time.time() + offset_steps * 30)


def _require_staff_2fa(tenant, owner):
    with tenant_context(tenant.id):
        platform_services.set_tenant_settings({"security.require_staff_2fa": True}, user=owner)
    cache.clear()


# --- Verification at sign-in ----------------------------------------------------------------------


@covers("auth-staff-mfa-verify")
def test_staff_with_2fa_needs_a_code_and_the_challenge_is_host_bound(tenant_a, tenant_b):
    user = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    make_membership(user, tenant_b, "OWNER")
    secret = enable_totp(user)
    first = _login("owner@example.com", "alpha.localhost").json()
    assert first["status"] == "mfa_required"
    assert "access" not in first

    # Tenant B's subdomain cannot finish a login that started on tenant A's.
    other = _post(
        "/api/v1/auth/staff/mfa/verify/",
        {"mfa_token": first["mfa_token"], "code": _code(secret)},
        "bravo.localhost",
    )
    assert other.json()["error"]["code"] == "TOKEN_INVALID"

    done = _post(
        "/api/v1/auth/staff/mfa/verify/",
        {"mfa_token": first["mfa_token"], "code": _code(secret)},
        "alpha.localhost",
    )
    assert done.status_code == 200
    assert done.json()["status"] == "authenticated"
    assert AccessToken(done.json()["access"])["tid"] == str(tenant_a.pk)
    assert "rt" in done.cookies


def test_a_code_works_once(tenant_a):
    user = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    secret = enable_totp(user)
    code = _code(secret)
    token = _login("owner@example.com", "alpha.localhost").json()["mfa_token"]
    assert (
        _post(
            "/api/v1/auth/staff/mfa/verify/", {"mfa_token": token, "code": code}, "alpha.localhost"
        ).status_code
        == 200
    )
    token2 = _login("owner@example.com", "alpha.localhost").json()["mfa_token"]
    replay = _post(
        "/api/v1/auth/staff/mfa/verify/", {"mfa_token": token2, "code": code}, "alpha.localhost"
    )
    assert replay.json()["error"]["code"] == "MFA_INVALID_CODE"


def test_wrong_codes_exhaust_the_challenge(tenant_a):
    user = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    secret = enable_totp(user)
    token = _login("owner@example.com", "alpha.localhost").json()["mfa_token"]
    for _ in range(5):
        wrong = _post(
            "/api/v1/auth/staff/mfa/verify/",
            {"mfa_token": token, "code": "000000"},
            "alpha.localhost",
        )
        assert wrong.json()["error"]["code"] == "MFA_INVALID_CODE"
    dead = _post(
        "/api/v1/auth/staff/mfa/verify/",
        {"mfa_token": token, "code": _code(secret)},
        "alpha.localhost",
    )
    assert dead.json()["error"]["code"] == "TOKEN_INVALID"


def test_recovery_code_signs_in_once_and_is_audited(tenant_a):
    user = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    enable_totp(user)
    from apps.accounts.mfa import replace_recovery_codes

    codes = replace_recovery_codes(user)
    token = _login("owner@example.com", "alpha.localhost").json()["mfa_token"]
    ok = _post(
        "/api/v1/auth/staff/mfa/verify/",
        {"mfa_token": token, "recovery_code": codes[0].upper()},
        "alpha.localhost",
    )
    assert ok.json()["status"] == "authenticated"
    token = _login("owner@example.com", "alpha.localhost").json()["mfa_token"]
    again = _post(
        "/api/v1/auth/staff/mfa/verify/",
        {"mfa_token": token, "recovery_code": codes[0]},
        "alpha.localhost",
    )
    assert again.json()["error"]["code"] == "MFA_INVALID_CODE"
    assert AuditLog.objects.filter(action="auth.recovery_code_used").count() == 1


def test_generic_domain_verifies_before_the_handoff(tenant_a):
    user = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    secret = enable_totp(user)
    token = _login("owner@example.com", "localhost").json()["mfa_token"]
    verified = _post(
        "/api/v1/auth/staff/mfa/verify/", {"mfa_token": token, "code": _code(secret)}, "localhost"
    ).json()
    assert verified["status"] == "handoff"
    exchanged = APIClient().post(
        "/api/v1/auth/handoff/exchange/",
        {"code": verified["handoff"]["code"]},
        format="json",
        HTTP_X_FORWARDED_HOST="alpha.localhost",
        HTTP_ORIGIN="http://alpha.localhost:3000",
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert exchanged.json()["status"] == "authenticated"  # no second prompt on the subdomain


# --- Enrolment (mandatory for super admin; tenant policy for staff) -------------------------------


def _enrol(start_body, host):
    started = _post(
        "/api/v1/auth/staff/mfa/enrol/start/",
        {"enrolment_token": start_body["enrolment_token"]},
        host,
    )
    assert started.status_code == 200
    secret = started.json()["secret"]
    assert started.json()["otpauth_uri"].startswith("otpauth://totp/")
    confirmed = _post(
        "/api/v1/auth/staff/mfa/enrol/confirm/",
        {"enrolment_token": start_body["enrolment_token"], "code": _code(secret)},
        host,
    )
    return secret, confirmed


@covers("auth-staff-mfa-enrol-start", "auth-staff-mfa-enrol-confirm")
def test_super_admin_must_enrol_and_gets_recovery_codes(tenant_a):
    admin = make_super_admin("root@platform.example.com")
    body = _login(admin.email, "admin.localhost").json()
    assert body["status"] == "mfa_setup_required"
    wrong_host = _post(
        "/api/v1/auth/staff/mfa/enrol/confirm/",
        {"enrolment_token": body["enrolment_token"], "code": "123456"},
        "alpha.localhost",
    )
    assert wrong_host.json()["error"]["code"] == "TOKEN_INVALID"

    secret, confirmed = _enrol(body, "admin.localhost")
    result = confirmed.json()
    assert result["status"] == "authenticated"
    assert len(result["recovery_codes"]) == 10
    assert "rt" in confirmed.cookies
    admin.refresh_from_db()
    assert admin.totp_enabled and admin.totp_secret == secret
    assert AuditLog.objects.filter(action="auth.mfa_enabled", target_id=str(admin.pk)).exists()
    # The pending secret was stored encrypted on the challenge, never in the payload.
    assert all("secret" not in c.payload for c in LoginChallenge.objects.all())

    # Next sign-in asks for a code instead of set-up.
    assert _login(admin.email, "admin.localhost").json()["status"] == "mfa_required"


def test_tenant_policy_requires_staff_to_enrol(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    make_staff_in(tenant_a, "SALES", email="sales@example.com")
    assert _login("sales@example.com", "alpha.localhost").json()["status"] == "authenticated"
    _require_staff_2fa(tenant_a, owner)
    body = _login("sales@example.com", "alpha.localhost").json()
    assert body["status"] == "mfa_setup_required"
    _, confirmed = _enrol(body, "alpha.localhost")
    assert confirmed.json()["status"] == "authenticated"


def test_tenant_policy_is_applied_at_handoff_exchange(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    _require_staff_2fa(tenant_a, owner)
    handoff = _login("owner@example.com", "localhost").json()
    assert handoff["status"] == "handoff"
    exchanged = APIClient().post(
        "/api/v1/auth/handoff/exchange/",
        {"code": handoff["handoff"]["code"]},
        format="json",
        HTTP_X_FORWARDED_HOST="alpha.localhost",
        HTTP_ORIGIN="http://alpha.localhost:3000",
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert exchanged.json()["status"] == "mfa_setup_required"


# --- Account security (authenticated) -------------------------------------------------------------


@covers("auth-mfa-setup", "auth-mfa-confirm")
def test_staff_can_turn_2fa_on_from_account_security(tenant_a):
    user = make_staff_in(tenant_a, "SALES", email="sales@example.com")
    access = issue_tokens(user, tenant_a.pk).access
    setup = _post("/api/v1/auth/mfa/setup/", {}, "alpha.localhost", access).json()
    wrong = _post(
        "/api/v1/auth/mfa/confirm/",
        {"setup_token": setup["setup_token"], "code": "000000"},
        "alpha.localhost",
        access,
    )
    assert wrong.json()["error"]["code"] == "MFA_INVALID_CODE"
    ok = _post(
        "/api/v1/auth/mfa/confirm/",
        {"setup_token": setup["setup_token"], "code": _code(setup["secret"])},
        "alpha.localhost",
        access,
    )
    assert ok.status_code == 200
    assert len(ok.json()["recovery_codes"]) == 10
    user.refresh_from_db()
    assert user.totp_enabled


@covers("auth-mfa-disable")
def test_disable_needs_password_and_code_and_is_refused_by_policy(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    secret = enable_totp(owner)
    access = issue_tokens(owner, tenant_a.pk).access
    bad_password = _post(
        "/api/v1/auth/mfa/disable/",
        {"password": "nope", "code": _code(secret)},
        "alpha.localhost",
        access,
    )
    assert bad_password.status_code == 400

    _require_staff_2fa(tenant_a, owner)
    refused = _post(
        "/api/v1/auth/mfa/disable/",
        {"password": PASSWORD, "code": _code(secret)},
        "alpha.localhost",
        access,
    )
    assert refused.json()["error"]["code"] == "MFA_REQUIRED_BY_POLICY"


def test_disable_turns_2fa_off_and_audits(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    secret = enable_totp(owner)
    access = issue_tokens(owner, tenant_a.pk).access
    response = _post(
        "/api/v1/auth/mfa/disable/",
        {"password": PASSWORD, "code": _code(secret)},
        "alpha.localhost",
        access,
    )
    assert response.status_code == 204
    owner.refresh_from_db()
    assert not owner.totp_enabled and owner.totp_secret == ""
    assert AuditLog.objects.filter(action="auth.mfa_disabled").exists()


def test_super_admin_cannot_disable_2fa():
    admin = make_super_admin()
    secret = enable_totp(admin)
    access = issue_tokens(admin, None).access
    refused = _post(
        "/api/v1/auth/mfa/disable/",
        {"password": PASSWORD, "code": _code(secret)},
        "admin.localhost",
        access,
    )
    assert refused.json()["error"]["code"] == "MFA_REQUIRED_BY_POLICY"


@covers("auth-mfa-recovery-codes")
def test_regenerating_recovery_codes_replaces_the_old_ones(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    secret = enable_totp(owner)
    from apps.accounts.mfa import replace_recovery_codes

    old = replace_recovery_codes(owner)
    access = issue_tokens(owner, tenant_a.pk).access
    response = _post(
        "/api/v1/auth/mfa/recovery-codes/",
        {"password": PASSWORD, "code": _code(secret)},
        "alpha.localhost",
        access,
    )
    new = response.json()["recovery_codes"]
    assert len(new) == 10 and not set(new) & set(old)
    assert RecoveryCode.objects.filter(user=owner).count() == 10


def test_retailers_cannot_use_staff_security_endpoints(tenant_a):
    retailer = User.objects.create_user(
        None, None, user_type=User.UserType.RETAILER, phone="9876543210"
    )
    access = issue_tokens(retailer, tenant_a.pk).access
    assert _post("/api/v1/auth/mfa/setup/", {}, "alpha.localhost", access).status_code == 403


def test_me_reports_2fa_state(tenant_a):
    admin = make_super_admin()
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(admin, None).access}")
    body = client.get("/api/v1/auth/me/", HTTP_X_FORWARDED_HOST="admin.localhost").json()
    assert body["mfa_enabled"] is False
    assert body["mfa_required"] is True


# --- Passwords ------------------------------------------------------------------------------------


def _reset_link():
    body = str(mail.outbox[-1].body)
    match = re.search(r"/reset-password/([^/\s]+)/([^/\s]+)", body)
    assert match, body
    return match.group(1), match.group(2)


@covers("auth-password-forgot", "auth-password-reset")
def test_forgot_and_reset_password_unlocks_and_ends_sessions(
    tenant_a, django_capture_on_commit_callbacks
):
    user = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    User.objects.filter(pk=user.pk).update(failed_login_count=3)
    old_session = issue_tokens(user, tenant_a.pk)
    with django_capture_on_commit_callbacks(execute=True):
        response = _post(
            "/api/v1/auth/password/forgot/", {"email": "OWNER@example.com"}, "localhost"
        )
    assert response.status_code == 202
    assert mail.outbox[-1].to == ["owner@example.com"]
    uid, token = _reset_link()
    assert "http://localhost" in mail.outbox[-1].body or "https://localhost" in mail.outbox[-1].body

    weak = _post(
        "/api/v1/auth/password/reset/",
        {"uid": uid, "token": token, "new_password": "123"},
        "localhost",
    )
    assert weak.status_code == 400
    assert "new_password" in weak.json()["error"]["details"]["fields"]

    ok = _post(
        "/api/v1/auth/password/reset/",
        {"uid": uid, "token": token, "new_password": "a-brand-new-passphrase"},
        "localhost",
    )
    assert ok.status_code == 204
    reused = _post(
        "/api/v1/auth/password/reset/",
        {"uid": uid, "token": token, "new_password": "yet-another-passphrase"},
        "localhost",
    )
    assert reused.json()["error"]["code"] == "TOKEN_INVALID"  # the link works once

    user.refresh_from_db()
    assert user.failed_login_count == 0 and user.locked_until is None
    refresh = APIClient().post(
        "/api/v1/auth/token/refresh/", {"refresh": old_session.refresh}, format="json"
    )
    assert refresh.status_code == 401  # every earlier session ended
    assert (
        _login("owner@example.com", "alpha.localhost", "a-brand-new-passphrase").json()["status"]
        == "authenticated"
    )
    assert AuditLog.objects.filter(action="auth.password_reset").exists()


def test_forgot_password_looks_the_same_for_unknown_emails(django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = _post(
            "/api/v1/auth/password/forgot/", {"email": "ghost@example.com"}, "localhost"
        )
    assert response.status_code == 202
    assert response.content == b""
    assert mail.outbox == []


def test_super_admin_reset_link_points_at_admin_host(django_capture_on_commit_callbacks):
    make_super_admin("root@platform.example.com")
    with django_capture_on_commit_callbacks(execute=True):
        _post(
            "/api/v1/auth/password/forgot/",
            {"email": "root@platform.example.com"},
            "admin.localhost",
        )
    assert "admin.localhost" in mail.outbox[-1].body


def test_forgot_password_is_rate_limited_per_email(django_capture_on_commit_callbacks):
    for _ in range(3):
        assert (
            _post(
                "/api/v1/auth/password/forgot/", {"email": "a@example.com"}, "localhost"
            ).status_code
            == 202
        )
    assert (
        _post("/api/v1/auth/password/forgot/", {"email": "a@example.com"}, "localhost").status_code
        == 429
    )


@covers("auth-password-change")
def test_change_password_keeps_this_session_and_ends_others(tenant_a):
    user = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    other_device = issue_tokens(user, tenant_a.pk)
    access = issue_tokens(user, tenant_a.pk).access
    wrong = _post(
        "/api/v1/auth/password/change/",
        {"current_password": "nope", "new_password": "a-brand-new-passphrase"},
        "alpha.localhost",
        access,
    )
    assert wrong.status_code == 400
    ok = _post(
        "/api/v1/auth/password/change/",
        {"current_password": PASSWORD, "new_password": "a-brand-new-passphrase"},
        "alpha.localhost",
        access,
    )
    assert ok.status_code == 200
    assert AccessToken(ok.json()["access"])["tid"] == str(tenant_a.pk)
    assert "rt" in ok.cookies
    assert (
        APIClient()
        .post("/api/v1/auth/token/refresh/", {"refresh": other_device.refresh}, format="json")
        .status_code
        == 401
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert client.get("/api/v1/auth/me/").status_code == 401  # old access token revoked too
