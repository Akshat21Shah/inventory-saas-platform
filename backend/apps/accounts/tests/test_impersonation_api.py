"""Support impersonation (spec 5.1, ADR-018, ADR-029)."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts import impersonation
from apps.accounts.models import ImpersonationSession, Membership
from apps.accounts.tests.factories import make_retailer_login, make_staff_in, make_super_admin
from apps.accounts.tokens import issue_tokens
from apps.audit.models import AuditLog
from apps.platform.models import Tenant, TenantBranding
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def admin():
    return make_super_admin("root@platform.example.com")


@pytest.fixture
def admin_api(admin):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(admin, None).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = "admin.localhost"
    return client


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    def _run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return _run


@pytest.fixture
def owner(tenant_a):
    user = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    with tenant_context(tenant_a.pk):
        TenantBranding.objects.create(display_name="Alpha")
    return user


def _start(admin_api, tenant, user, reason="Customer asked for help with branding"):
    return admin_api.post(
        "/api/v1/platform/impersonations/",
        {"tenant_id": str(tenant.pk), "user_id": str(user.pk), "reason": reason},
        format="json",
    )


def _enter(admin_api, tenant, user):
    """Start a session and exchange its handoff on the tenant subdomain; returns a client."""
    started = _start(admin_api, tenant, user)
    assert started.status_code == 201, started.json()
    host = f"{tenant.slug}.localhost"
    exchanged = APIClient().post(
        "/api/v1/auth/handoff/exchange/",
        {"code": started.json()["handoff_code"]},
        format="json",
        HTTP_X_FORWARDED_HOST=host,
        HTTP_ORIGIN=f"http://{host}:3000",
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert exchanged.status_code == 200, exchanged.json()
    assert "rt" not in exchanged.cookies  # never refreshable
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {exchanged.json()['access']}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = host
    return client, exchanged.json()["access"], started.json()


# --- Starting -----------------------------------------------------------------------------------


@covers("platform-impersonations")
def test_start_needs_a_reason_and_a_valid_target(admin_api, tenant_a, tenant_b, owner):
    assert (
        "reason"
        in _start(admin_api, tenant_a, owner, reason=" ").json()["error"]["details"]["fields"]
    )
    other_admin = make_super_admin()
    assert (
        "user_id" in _start(admin_api, tenant_a, other_admin).json()["error"]["details"]["fields"]
    )
    assert (
        "user_id" in _start(admin_api, tenant_b, owner).json()["error"]["details"]["fields"]
    )  # not B's staff
    started = _start(admin_api, tenant_a, owner)
    assert started.status_code == 201
    assert started.json()["tenant_slug"] == tenant_a.slug
    assert started.json()["target_type"] == "STAFF"


def test_only_platform_users_with_the_permission_can_start(tenant_a, owner):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(owner, tenant_a.pk).access}")
    response = client.post(
        "/api/v1/platform/impersonations/",
        {"tenant_id": str(tenant_a.pk), "user_id": str(owner.pk), "reason": "x"},
        format="json",
        HTTP_X_FORWARDED_HOST="alpha.localhost",
    )
    assert response.status_code == 403


def test_session_token_carries_the_impersonation_and_ends_with_the_session(
    admin_api, admin, tenant_a, owner
):
    client, access, _ = _enter(admin_api, tenant_a, owner)
    claims = AccessToken(access)
    assert claims["sub"] == str(owner.pk)
    assert claims["tid"] == str(tenant_a.pk)
    assert claims["imp_by"] == str(admin.pk)
    session = ImpersonationSession.objects.unscoped().get()
    assert abs(claims["exp"] - int(session.expires_at.timestamp())) <= 1
    assert session.expires_at - session.created_at <= timedelta(minutes=30, seconds=1)
    me = client.get("/api/v1/auth/me/").json()
    assert me["impersonation"]["mode"] == "READ_ONLY"
    assert me["impersonation"]["impersonator_id"] == str(admin.pk)
    no_refresh = APIClient().post(
        "/api/v1/auth/token/refresh/",
        {},
        format="json",
        HTTP_X_FORWARDED_HOST="alpha.localhost",
        HTTP_ORIGIN="http://alpha.localhost:3000",
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert no_refresh.status_code == 401  # no refresh cookie was ever issued


# --- Read-only, act mode and always-blocked actions ---------------------------------------------


def test_read_only_session_refuses_every_write(admin_api, tenant_a, owner):
    client, _, _ = _enter(admin_api, tenant_a, owner)
    assert client.get("/api/v1/settings/branding/").status_code == 200
    for method, path, body in (
        ("patch", "/api/v1/settings/branding/", {"display_name": "Changed"}),
        ("patch", "/api/v1/auth/me/", {"full_name": "Changed"}),
    ):
        response = getattr(client, method)(path, body, format="json")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "IMPERSONATION_READ_ONLY"


@covers("auth-impersonation-act")
def test_act_mode_needs_a_reason_and_every_write_is_audited(admin_api, admin, tenant_a, owner, run):
    client, _, _ = _enter(admin_api, tenant_a, owner)
    assert (
        client.post("/api/v1/auth/impersonation/act/", {"reason": ""}, format="json").status_code
        == 400
    )
    acted = client.post(
        "/api/v1/auth/impersonation/act/",
        {"reason": "Fix the colour they asked for"},
        format="json",
    )
    assert acted.status_code == 200
    changed = run(
        client.patch, "/api/v1/settings/branding/", {"primary_color": "#0f766e"}, format="json"
    )
    assert changed.status_code == 200, changed.json()

    branding_entry = AuditLog.objects.get(action="settings.branding_changed")
    assert branding_entry.actor_id == owner.pk
    assert branding_entry.impersonator_id == admin.pk
    write_entry = AuditLog.objects.get(action="impersonation.write")
    assert write_entry.tenant_id == tenant_a.pk
    assert write_entry.metadata["path"] == "/api/v1/settings/branding/"
    act_entry = AuditLog.objects.get(action="impersonation.act_enabled")
    assert act_entry.metadata["reason"] == "Fix the colour they asked for"
    assert act_entry.actor_id == admin.pk


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/api/v1/staff/invitations/", {"email": "x@example.com", "role_code": "SALES"}),
        ("put", "/api/v1/settings/bank-details/", {"bank_account_number": "1234567890"}),
        ("post", "/api/v1/auth/password/change/", {"current_password": "a", "new_password": "b"}),
        ("post", "/api/v1/auth/mfa/setup/", {}),
    ],
)
def test_credentials_staff_and_bank_details_stay_blocked_in_act_mode(
    admin_api, tenant_a, owner, method, path, body
):
    client, _, _ = _enter(admin_api, tenant_a, owner)
    client.post("/api/v1/auth/impersonation/act/", {"reason": "Support ticket 42"}, format="json")
    response = getattr(client, method)(path, body, format="json")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "IMPERSONATION_BLOCKED"


def test_reading_staff_is_allowed_in_a_session(admin_api, tenant_a, owner):
    client, _, _ = _enter(admin_api, tenant_a, owner)
    assert client.get("/api/v1/staff/").status_code == 200


# --- Ending, expiry, hosts, suspended tenants ---------------------------------------------------


@covers("auth-impersonation-end")
def test_ending_the_session_invalidates_its_token(admin_api, tenant_a, owner):
    client, _, _ = _enter(admin_api, tenant_a, owner)
    assert client.post("/api/v1/auth/impersonation/end/").status_code == 204
    assert client.get("/api/v1/auth/me/").status_code == 401
    session = ImpersonationSession.objects.unscoped().get()
    assert session.end_reason == "ENDED" and session.ended_at is not None
    assert AuditLog.objects.filter(action="impersonation.ended", tenant=tenant_a).exists()


def test_expired_sessions_stop_working_and_are_recorded(admin_api, tenant_a, owner):
    client, _, _ = _enter(admin_api, tenant_a, owner)
    ImpersonationSession.objects.unscoped().update(expires_at=timezone.now() - timedelta(seconds=1))
    assert client.get("/api/v1/auth/me/").status_code == 401
    assert impersonation.expire_sessions() == 1
    assert ImpersonationSession.objects.unscoped().get().end_reason == "EXPIRED"
    assert AuditLog.objects.filter(action="impersonation.expired", tenant=tenant_a).exists()


def test_session_token_only_works_on_its_tenant_subdomain(admin_api, tenant_a, owner):
    _, access, _ = _enter(admin_api, tenant_a, owner)
    other = APIClient()
    other.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert other.get("/api/v1/auth/me/", HTTP_X_FORWARDED_HOST="bravo.localhost").status_code == 401


def test_support_can_look_at_a_suspended_tenant(admin_api, tenant_a, owner):
    Tenant.objects.filter(pk=tenant_a.pk).update(status=Tenant.Status.SUSPENDED)
    cache.clear()
    owner_client = APIClient()
    owner_client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(owner, tenant_a.pk).access}")
    assert owner_client.get("/api/v1/auth/me/").json()["error"]["code"] == "TENANT_SUSPENDED"
    client, _, _ = _enter(admin_api, tenant_a, owner)
    assert client.get("/api/v1/auth/me/").status_code == 200


def test_retailers_can_be_impersonated(admin_api, tenant_a, run):
    retailer = make_retailer_login(tenant_a, "9876543210", "Ganesh Kirana")
    client, _, started = _enter(admin_api, tenant_a, retailer)
    assert started["target_type"] == "RETAILER"
    assert client.get("/api/v1/auth/me/").json()["retailer"]["shop_name"] == "Ganesh Kirana"


# --- Visibility ---------------------------------------------------------------------------------


def test_owners_see_support_sessions_in_their_own_audit_log(admin_api, tenant_a, tenant_b, owner):
    client, _, _ = _enter(admin_api, tenant_a, owner)
    client.post("/api/v1/auth/impersonation/act/", {"reason": "Ticket 7"}, format="json")
    client.post("/api/v1/auth/impersonation/end/")
    owner_client = APIClient()
    owner_client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(owner, tenant_a.pk).access}")
    actions = {
        e["action"]
        for e in owner_client.get("/api/v1/audit-logs/", {"action": "impersonation."}).json()[
            "results"
        ]
    }
    assert actions == {"impersonation.started", "impersonation.act_enabled", "impersonation.ended"}
    owner_b = make_staff_in(tenant_b, "OWNER")
    b_client = APIClient()
    b_client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(owner_b, tenant_b.pk).access}")
    assert b_client.get("/api/v1/audit-logs/", {"action": "impersonation."}).json()["results"] == []


def test_platform_history_lists_sessions_across_tenants(admin_api, tenant_a, tenant_b, owner):
    _start(admin_api, tenant_a, owner)
    _start(admin_api, tenant_b, make_staff_in(tenant_b, "OWNER"))
    rows = admin_api.get("/api/v1/platform/impersonations/").json()["results"]
    assert {r["tenant"]["slug"] for r in rows} == {tenant_a.slug, tenant_b.slug}
    assert all(r["reason"] for r in rows)


def test_membership_reference_kept(tenant_a, owner):
    assert Membership.objects.unscoped().filter(user=owner).exists()


# --- ADR-029: every endpoint in the protected groups is marked ----------------------------------

BLOCKED_ROUTE_NAMES = {
    "staff-list",
    "staff-detail",
    "staff-invitations",
    "staff-invitation-resend",
    "staff-invitation-revoke",
    "auth-mfa-setup",
    "auth-mfa-confirm",
    "auth-mfa-disable",
    "auth-mfa-recovery-codes",
    "auth-password-change",
    "settings-bank-details",
}


def _views_by_name():
    found = {}

    def walk(patterns):
        for p in patterns:
            if isinstance(p, URLResolver):
                walk(p.url_patterns)
            elif isinstance(p, URLPattern) and p.name:
                found[p.name] = getattr(p.callback, "view_class", None) or getattr(
                    p.callback, "cls", None
                )

    walk(get_resolver().url_patterns)
    return found


def test_every_protected_endpoint_is_marked_impersonation_blocked():
    views = _views_by_name()
    missing = sorted(
        n for n in BLOCKED_ROUTE_NAMES if not getattr(views.get(n), "impersonation_blocked", False)
    )
    assert missing == []
    staff_and_security = {
        n for n in views if n.startswith(("staff-", "auth-mfa-", "auth-password-change"))
    }
    assert staff_and_security <= BLOCKED_ROUTE_NAMES, "new staff/security routes must be marked too"
