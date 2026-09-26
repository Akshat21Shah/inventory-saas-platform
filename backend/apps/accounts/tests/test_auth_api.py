"""Staff authentication API (spec 5.2, ADR-020, ADR-025, ADR-030)."""

import threading
import types
from datetime import timedelta

import pytest
from django.core import mail
from django.core.cache import cache
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts import services
from apps.accounts.models import HandoffCode, LoginChallenge, Membership, User
from apps.accounts.tests.factories import (
    make_membership,
    make_retailer_login,
    make_staff_in,
    make_super_admin,
)
from apps.accounts.tokens import issue_tokens
from apps.audit.models import AuditLog
from apps.platform import services as platform_services
from apps.platform.models import Tenant
from apps.platform.tests.factories import TenantFactory
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/staff/login/"
CHOOSE = "/api/v1/auth/staff/choose-tenant/"
EXCHANGE = "/api/v1/auth/handoff/exchange/"
REFRESH = "/api/v1/auth/token/refresh/"
LOGOUT = "/api/v1/auth/logout/"
ME = "/api/v1/auth/me/"
PASSWORD = "a-strong-password"


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


def _host(tenant):
    return f"{tenant.slug}.localhost"


def _login(client, email, password=PASSWORD, host="localhost", ip="198.51.100.10"):
    return client.post(
        LOGIN,
        {"email": email, "password": password},
        format="json",
        HTTP_X_FORWARDED_HOST=host,
        HTTP_X_FORWARDED_FOR=ip,
    )


def _browser(host):
    """Headers a same-origin browser fetch would send (cookie-authenticated endpoints)."""
    return {
        "HTTP_X_FORWARDED_HOST": host,
        "HTTP_ORIGIN": f"http://{host}:3000",
        "HTTP_X_REQUESTED_WITH": "fetch",
    }


def _claims(access):
    return AccessToken(access)


# --- Credentials & host rules ------------------------------------------------------------------


@covers("auth-staff-login")
def test_staff_signs_in_on_own_tenant_subdomain(tenant_a):
    user = make_staff_in(tenant_a, "MANAGER", email="manager@example.com")
    response = _login(APIClient(), "Manager@Example.com ", host=_host(tenant_a))
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["status"] == "authenticated"
    claims = _claims(body["access"])
    assert claims["sub"] == str(user.pk)
    assert claims["tid"] == str(tenant_a.pk)
    assert claims["utype"] == "STAFF"
    cookie = response.cookies["rt"]
    assert cookie["httponly"] is True
    assert cookie["path"] == "/api/v1/auth/"
    assert cookie["samesite"] == "Lax"
    assert cookie["domain"] == ""  # host-only: never sent to other subdomains
    assert cookie["secure"] is True
    assert "refresh" not in body  # the refresh token only travels in the httpOnly cookie
    user.refresh_from_db()
    assert user.last_login is not None


@covers("auth-staff-login")
def test_staff_cannot_sign_in_on_another_tenants_subdomain(tenant_a, tenant_b):
    make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    wrong_password = _login(APIClient(), "owner@example.com", "not-the-password", _host(tenant_a))
    other_tenant = _login(APIClient(), "owner@example.com", host=_host(tenant_b))
    assert other_tenant.status_code == 400
    assert other_tenant.json() == wrong_password.json()  # indistinguishable from a wrong password
    assert other_tenant.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert "rt" not in other_tenant.cookies


def test_unknown_email_and_wrong_password_look_identical(tenant_a):
    make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    unknown = _login(APIClient(), "nobody@example.com", host=_host(tenant_a))
    wrong = _login(APIClient(), "owner@example.com", "nope-nope-nope", host=_host(tenant_a))
    assert unknown.status_code == wrong.status_code == 400
    assert unknown.json() == wrong.json()


def test_super_admin_signs_in_only_on_admin_host(tenant_a):
    admin = make_super_admin("root@platform.example.com")
    ok = _login(APIClient(), admin.email, host="admin.localhost")
    assert ok.status_code == 200
    assert ok.json()["status"] == "mfa_setup_required"  # 2FA is mandatory for super admins
    for host in (_host(tenant_a), "localhost", "evil.example.com"):
        refused = _login(APIClient(), admin.email, host=host)
        assert refused.json()["error"]["code"] == "INVALID_CREDENTIALS", host


def test_staff_are_refused_on_admin_host(tenant_a):
    make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    assert _login(APIClient(), "owner@example.com", host="admin.localhost").status_code == 400


def test_inactive_membership_or_user_cannot_sign_in(tenant_a):
    user = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    Membership.objects.unscoped().filter(user=user).update(is_active=False)
    assert _login(APIClient(), "owner@example.com", host=_host(tenant_a)).status_code == 400
    Membership.objects.unscoped().filter(user=user).update(is_active=True)
    User.objects.filter(pk=user.pk).update(is_active=False)
    assert _login(APIClient(), "owner@example.com", host=_host(tenant_a)).status_code == 400


NEUTRAL = "This account is currently unavailable. Please contact your distributor."


@pytest.mark.parametrize("status", [Tenant.Status.SUSPENDED, Tenant.Status.ONBOARDING])
def test_unavailable_tenant_gets_one_neutral_answer_for_every_attempt(tenant_a, status):
    make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    Tenant.objects.filter(pk=tenant_a.pk).update(status=status)
    for password in (PASSWORD, "wrong-password-1"):
        response = _login(APIClient(), "owner@example.com", password, host=_host(tenant_a))
        assert response.status_code == 403
        assert response.json()["error"] == {
            "code": "TENANT_UNAVAILABLE",
            "message": NEUTRAL,
            "details": {},
        }
    body = APIClient().get(f"/api/v1/public/tenants/{tenant_a.slug}/branding/").json()
    assert body["available"] is False
    assert "status" not in body  # the specific state is never disclosed


# --- Lockout & rate limits (ADR-030) ------------------------------------------------------------


@pytest.fixture
def generous_email_limit(staff_user, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        platform_services.set_platform_settings(
            {"platform.login_rate_per_email_per_minute": 60}, user=staff_user
        )


def test_five_failures_lock_the_account_and_email_the_user(
    tenant_a, generous_email_limit, django_capture_on_commit_callbacks
):
    user = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    with django_capture_on_commit_callbacks(execute=True):
        for _ in range(5):
            _login(APIClient(), "owner@example.com", "wrong-password-1", _host(tenant_a))
    user.refresh_from_db()
    assert user.is_locked()
    assert user.failed_login_count == 0
    locked = _login(APIClient(), "owner@example.com", host=_host(tenant_a))  # right password
    assert locked.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["owner@example.com"]
    assert "paused" in mail.outbox[0].subject
    assert AuditLog.objects.filter(action="auth.account_locked", target_id=str(user.pk)).exists()

    User.objects.filter(pk=user.pk).update(locked_until=timezone.now() - timedelta(seconds=1))
    assert _login(APIClient(), "owner@example.com", host=_host(tenant_a)).status_code == 200


def test_success_resets_the_failure_count(tenant_a, generous_email_limit):
    user = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    for _ in range(4):
        _login(APIClient(), "owner@example.com", "wrong-password-1", _host(tenant_a))
    user.refresh_from_db()
    assert user.failed_login_count == 4
    assert _login(APIClient(), "owner@example.com", host=_host(tenant_a)).status_code == 200
    user.refresh_from_db()
    assert user.failed_login_count == 0


def test_lockout_threshold_is_a_platform_setting(
    tenant_a, staff_user, generous_email_limit, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        platform_services.set_platform_settings(
            {"platform.login_lockout_threshold": 3}, user=staff_user
        )
    user = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    for _ in range(3):
        _login(APIClient(), "owner@example.com", "wrong-password-1", _host(tenant_a))
    user.refresh_from_db()
    assert user.is_locked()


def test_per_email_rate_limit(tenant_a):
    make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    for i in range(5):
        _login(APIClient(), "owner@example.com", "wrong", _host(tenant_a), ip=f"198.51.100.{i}")
    limited = _login(APIClient(), "owner@example.com", host=_host(tenant_a), ip="198.51.100.99")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert int(limited["Retry-After"]) >= 1


def test_per_ip_limit_is_generous_for_shared_mobile_ips(tenant_a, monkeypatch):
    """30 attempts per minute from one IP (CGNAT), across different accounts."""
    # Fixed windows: keep all 31 attempts in one minute even if the run crosses a boundary.
    frozen = types.SimpleNamespace(time=lambda: 1_800_000_010.0)
    monkeypatch.setattr("common.ratelimit.time", frozen)  # only the limiter's clock
    for i in range(30):
        response = _login(
            APIClient(), f"user{i}@example.com", host=_host(tenant_a), ip="203.0.113.5"
        )
        assert response.status_code == 400
    assert (
        _login(APIClient(), "late@example.com", host=_host(tenant_a), ip="203.0.113.5").status_code
        == 429
    )
    assert (
        _login(APIClient(), "late@example.com", host=_host(tenant_a), ip="203.0.113.6").status_code
        == 400
    )


# --- Generic domain: handoff and tenant chooser (ADR-020) ---------------------------------------


@covers("auth-handoff-exchange")
def test_generic_domain_hands_single_tenant_session_to_its_subdomain(tenant_a, tenant_b):
    make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    response = _login(APIClient(), "owner@example.com", host="localhost")
    body = response.json()
    assert body["status"] == "handoff"
    assert body["handoff"]["tenant_slug"] == tenant_a.slug
    assert "access" not in body
    assert "rt" not in response.cookies
    code = body["handoff"]["code"]

    wrong_host = APIClient().post(
        EXCHANGE, {"code": code}, format="json", **_browser(_host(tenant_b))
    )
    assert wrong_host.json()["error"]["code"] == "TOKEN_INVALID"  # and the code is now spent

    fresh = _login(APIClient(), "owner@example.com", host="localhost").json()["handoff"]["code"]
    client = APIClient()
    exchanged = client.post(EXCHANGE, {"code": fresh}, format="json", **_browser(_host(tenant_a)))
    assert exchanged.status_code == 200
    assert _claims(exchanged.json()["access"])["tid"] == str(tenant_a.pk)
    assert "rt" in exchanged.cookies
    again = client.post(EXCHANGE, {"code": fresh}, format="json", **_browser(_host(tenant_a)))
    assert again.json()["error"]["code"] == "TOKEN_INVALID"


def test_handoff_code_expires_after_60_seconds(tenant_a):
    make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    code = _login(APIClient(), "owner@example.com").json()["handoff"]["code"]
    HandoffCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    response = APIClient().post(
        EXCHANGE, {"code": code}, format="json", **_browser(_host(tenant_a))
    )
    assert response.json()["error"]["code"] == "TOKEN_INVALID"


def test_handoff_exchange_requires_same_origin(tenant_a):
    make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    code = _login(APIClient(), "owner@example.com").json()["handoff"]["code"]
    headers = _browser(_host(tenant_a)) | {"HTTP_ORIGIN": "http://evil.example.com"}
    response = APIClient().post(EXCHANGE, {"code": code}, format="json", **headers)
    assert response.status_code == 403


@covers("auth-staff-choose-tenant")
def test_multi_tenant_staff_choose_among_their_active_tenants_only(tenant_a, tenant_b):
    user = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    make_membership(user, tenant_b, "SALES")
    suspended = TenantFactory.create(name="Zeta", status=Tenant.Status.SUSPENDED)
    make_membership(user, suspended, "OWNER")
    stranger = TenantFactory.create(name="Stranger")

    body = _login(APIClient(), "owner@example.com").json()
    assert body["status"] == "choose_tenant"
    assert {t["slug"] for t in body["tenants"]} == {tenant_a.slug, tenant_b.slug}

    not_mine = APIClient().post(
        CHOOSE, {"choice_token": body["choice_token"], "tenant_id": str(stranger.pk)}, format="json"
    )
    assert not_mine.json()["error"]["code"] == "TOKEN_INVALID"

    token = _login(APIClient(), "owner@example.com").json()["choice_token"]
    chosen = APIClient().post(
        CHOOSE, {"choice_token": token, "tenant_id": str(tenant_b.pk)}, format="json"
    )
    assert chosen.json()["status"] == "handoff"
    assert chosen.json()["handoff"]["tenant_slug"] == tenant_b.slug
    reused = APIClient().post(
        CHOOSE, {"choice_token": token, "tenant_id": str(tenant_a.pk)}, format="json"
    )
    assert reused.json()["error"]["code"] == "TOKEN_INVALID"


def test_generic_domain_with_only_unavailable_tenants_says_so(tenant_a):
    make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    Tenant.objects.filter(pk=tenant_a.pk).update(status=Tenant.Status.SUSPENDED)
    assert _login(APIClient(), "owner@example.com").json()["error"]["code"] == "TENANT_UNAVAILABLE"


# --- Refresh, logout (ADR-025) ------------------------------------------------------------------


def _signed_in(tenant, role="OWNER", email="owner@example.com"):
    user = make_staff_in(tenant, role, email=email)
    client = APIClient()
    response = _login(client, email, host=_host(tenant))
    assert response.status_code == 200
    return user, client, response


@covers("auth-token-refresh")
def test_refresh_rotates_the_cookie_and_keeps_the_tenant(tenant_a, tenant_b):
    _, client, first = _signed_in(tenant_a)
    old_refresh = first.cookies["rt"].value
    response = client.post(REFRESH, {}, format="json", **_browser(_host(tenant_a)))
    assert response.status_code == 200
    assert _claims(response.json()["access"])["tid"] == str(tenant_a.pk)  # never another tenant
    assert response.cookies["rt"].value != old_refresh
    assert "refresh" not in response.json()

    replay = APIClient()
    replay.cookies["rt"] = old_refresh
    reused = replay.post(REFRESH, {}, format="json", **_browser(_host(tenant_a)))
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "SESSION_EXPIRED"


def test_refresh_with_cookie_requires_same_origin(tenant_a):
    _, client, _ = _signed_in(tenant_a)
    no_header = client.post(REFRESH, {}, format="json", HTTP_X_FORWARDED_HOST=_host(tenant_a))
    assert no_header.status_code == 403
    cross = client.post(
        REFRESH,
        {},
        format="json",
        **(_browser(_host(tenant_a)) | {"HTTP_ORIGIN": "http://evil.test"}),
    )
    assert cross.status_code == 403


def test_refresh_in_body_returns_the_new_refresh_in_body(tenant_a):
    user = make_staff_in(tenant_a, "OWNER")
    tokens = issue_tokens(user, tenant_a.pk)
    response = APIClient().post(REFRESH, {"refresh": tokens.refresh}, format="json")
    assert response.status_code == 200
    assert response.json()["refresh"] != tokens.refresh
    assert "rt" not in response.cookies


def test_staff_session_does_not_slide_but_retailer_session_does(tenant_a):
    staff = make_staff_in(tenant_a, "OWNER")
    started = issue_tokens(staff, tenant_a.pk)
    rotated = APIClient().post(REFRESH, {"refresh": started.refresh}, format="json").json()
    original = RefreshToken(started.refresh, verify=False)  # type: ignore[arg-type]
    assert RefreshToken(rotated["refresh"])["exp"] == original["exp"]
    assert started.session_expires_at is not None

    retailer = make_retailer_login(tenant_a)
    first = issue_tokens(retailer, tenant_a.pk)
    assert first.session_expires_at is None
    assert first.refresh_expires_at - timezone.now() > timedelta(days=29)


def test_refresh_fails_after_membership_deactivated_or_tenant_suspended(tenant_a):
    user = make_staff_in(tenant_a, "OWNER")
    tokens = issue_tokens(user, tenant_a.pk)
    Membership.objects.unscoped().filter(user=user).update(is_active=False)
    response = APIClient().post(REFRESH, {"refresh": tokens.refresh}, format="json")
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"

    Membership.objects.unscoped().filter(user=user).update(is_active=True)
    tokens = issue_tokens(user, tenant_a.pk)
    Tenant.objects.filter(pk=tenant_a.pk).update(status=Tenant.Status.SUSPENDED)
    response = APIClient().post(REFRESH, {"refresh": tokens.refresh}, format="json")
    assert response.json()["error"]["code"] == "TENANT_UNAVAILABLE"


@pytest.mark.django_db(transaction=True)
def test_concurrent_refresh_with_the_same_token_succeeds_once(tenant_a):
    user = make_staff_in(tenant_a, "OWNER")
    tokens = issue_tokens(user, tenant_a.pk)
    barrier = threading.Barrier(4)
    statuses: list[int] = []

    def worker() -> None:
        barrier.wait()
        response = APIClient().post(REFRESH, {"refresh": tokens.refresh}, format="json")
        statuses.append(response.status_code)
        connection.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(statuses) == [200, 401, 401, 401]


@covers("auth-logout")
def test_logout_revokes_the_refresh_token_and_clears_the_cookie(tenant_a):
    _, client, first = _signed_in(tenant_a)
    refresh = first.cookies["rt"].value
    response = client.post(LOGOUT, {}, format="json", **_browser(_host(tenant_a)))
    assert response.status_code == 204
    assert response.cookies["rt"].value == ""
    replay = APIClient()
    replay.cookies["rt"] = refresh
    assert replay.post(REFRESH, {}, format="json", **_browser(_host(tenant_a))).status_code == 401


def test_logout_requires_same_origin_for_cookie(tenant_a):
    _, client, _ = _signed_in(tenant_a)
    assert (
        client.post(LOGOUT, {}, format="json", HTTP_X_FORWARDED_HOST=_host(tenant_a)).status_code
        == 403
    )


# --- Me & per-request checks --------------------------------------------------------------------


def _bearer(client, access):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


@covers("auth-me")
def test_me_describes_the_user_in_the_token_tenant_only(tenant_a, tenant_b):
    user = make_staff_in(tenant_a, "WAREHOUSE", email="wh@example.com")
    make_membership(user, tenant_b, "OWNER")
    access = issue_tokens(user, tenant_a.pk).access
    body = _bearer(APIClient(), access).get(ME, HTTP_X_FORWARDED_HOST=_host(tenant_a)).json()
    assert body["tenant"]["id"] == str(tenant_a.pk)
    assert body["role"] == {"code": "WAREHOUSE", "name": "Warehouse"}
    assert "stock.adjust" in body["permissions"]
    assert "staff.manage" not in body["permissions"]  # the OWNER role is in tenant B only
    assert set(body["features"]) >= {"payments", "ai"}
    assert body["impersonation"] is None

    wrong_host = _bearer(APIClient(), access).get(ME, HTTP_X_FORWARDED_HOST=_host(tenant_b))
    assert wrong_host.status_code == 401


def test_me_for_super_admin_has_platform_permissions_and_no_tenant():
    admin = make_super_admin()
    access = issue_tokens(admin, None).access
    body = _bearer(APIClient(), access).get(ME, HTTP_X_FORWARDED_HOST="admin.localhost").json()
    assert body["tenant"] is None
    assert "platform.tenants.manage" in body["permissions"]
    assert (
        _bearer(APIClient(), access).get(ME, HTTP_X_FORWARDED_HOST="alpha.localhost").status_code
        == 401
    )


def test_me_update_changes_name_and_language(tenant_a):
    user = make_staff_in(tenant_a, "SALES")
    client = _bearer(APIClient(), issue_tokens(user, tenant_a.pk).access)
    response = client.patch(
        ME, {"full_name": " Asha Rao ", "preferred_language": "mr"}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Asha Rao"
    assert response.json()["preferred_language"] == "mr"
    bad = client.patch(ME, {"preferred_language": "fr"}, format="json")
    assert bad.status_code == 400


def test_deactivation_and_suspension_take_effect_on_the_next_request(tenant_a):
    user = make_staff_in(tenant_a, "OWNER")
    client = _bearer(APIClient(), issue_tokens(user, tenant_a.pk).access)
    assert client.get(ME).status_code == 200
    Membership.objects.unscoped().filter(user=user).update(is_active=False)
    assert client.get(ME).status_code == 401
    Membership.objects.unscoped().filter(user=user).update(is_active=True)
    Tenant.objects.filter(pk=tenant_a.pk).update(status=Tenant.Status.SUSPENDED)
    cache.clear()  # the suspension service invalidates the cached tenant status
    suspended = client.get(ME)
    assert suspended.status_code == 403
    assert suspended.json()["error"]["code"] == "TENANT_UNAVAILABLE"


def test_password_change_revokes_existing_access_tokens(tenant_a):
    user = make_staff_in(tenant_a, "OWNER")
    client = _bearer(APIClient(), issue_tokens(user, tenant_a.pk).access)
    assert client.get(ME).status_code == 200
    user.set_password("a-completely-new-password")
    user.save()
    assert client.get(ME).status_code == 401


def test_staff_token_without_tenant_is_rejected(tenant_a):
    user = make_staff_in(tenant_a, "OWNER")
    assert _bearer(APIClient(), issue_tokens(user, None).access).get(ME).status_code == 401


def test_purge_removes_old_login_records(tenant_a):
    user = make_staff_in(tenant_a, "OWNER")
    old = timezone.now() - timedelta(days=2)
    LoginChallenge.objects.create(kind="MFA", token_hash="a" * 64, user=user, expires_at=old)
    HandoffCode.objects.create(code_hash="b" * 64, user=user, tenant=tenant_a, expires_at=old)
    assert services.purge_expired_login_records() == 2


# --- Forwarded headers (ADR-032) ------------------------------------------------------------------


def test_spoofed_x_forwarded_for_does_not_change_the_rate_limited_ip(tenant_a):
    """A browser talking to Django directly (not through the trusted Next.js proxy) cannot pick
    its own IP: 30 attempts with 30 different spoofed addresses still share one per-IP bucket."""
    for i in range(30):
        response = APIClient().post(
            LOGIN,
            {"email": f"user{i}@example.com", "password": "x"},
            format="json",
            REMOTE_ADDR="203.0.113.50",
            HTTP_X_FORWARDED_FOR=f"198.51.100.{i}",
            HTTP_X_FORWARDED_HOST="alpha.localhost",
        )
        assert response.status_code == 400
    blocked = APIClient().post(
        LOGIN,
        {"email": "late@example.com", "password": "x"},
        format="json",
        REMOTE_ADDR="203.0.113.50",
        HTTP_X_FORWARDED_FOR="192.0.2.77",
    )
    assert blocked.status_code == 429


def test_forwarded_ip_from_the_trusted_proxy_is_used(tenant_a):
    """Through the Next.js proxy (trusted), each real client gets its own bucket."""
    for _ in range(30):
        APIClient().post(
            LOGIN,
            {"email": "a@example.com", "password": "x"},
            format="json",
            HTTP_X_FORWARDED_FOR="198.51.100.1",
        )
    other_client = APIClient().post(
        LOGIN,
        {"email": "b@example.com", "password": "x"},
        format="json",
        HTTP_X_FORWARDED_FOR="198.51.100.2",
    )
    assert other_client.status_code == 400  # not limited by the first client's attempts
