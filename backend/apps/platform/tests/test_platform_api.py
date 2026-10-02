"""Super admin API (spec 5.1, PLAN §3.3, ADR-018, ADR-030)."""

import re

import pytest
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.accounts.models import Invitation, Membership
from apps.accounts.tests.factories import make_retailer_login, make_staff_in, make_super_admin
from apps.accounts.tokens import issue_tokens
from apps.audit.models import AuditLog
from apps.platform.models import (
    FeatureFlag,
    HsnRateHint,
    Plan,
    Subscription,
    TaxRate,
    Tenant,
    TenantBranding,
    TenantFeature,
    TenantProfile,
)
from apps.platform.selectors import current_plan, effective_features
from apps.platform.tests.factories import make_gstin
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
P = "/api/v1/platform"


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def admin():
    return make_super_admin("root@platform.example.com")


@pytest.fixture
def api(admin):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(admin, None).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = "admin.localhost"
    return client


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    """Run a request and its on-commit work (emails, cache invalidation)."""

    def _run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return _run


def _invite_token():
    match = re.search(r"/invite/(\S+)", str(mail.outbox[-1].body))
    assert match is not None
    return match.group(1)


def _payload(**overrides):
    body = {
        "name": "Mehta Wholesale",
        "legal_name": "Mehta Wholesale Private Limited",
        "gstin": make_gstin(4242, "27"),
        "state_code": "27",
        "address_line1": "Plot 7, MIDC",
        "city": "Nashik",
        "pincode": "422007",
        "email": "Accounts@Mehta.example.com",
        "phone": "02532345678",
        "slug": "mehta",
        "owner_email": "owner@mehta.example.com",
        "owner_name": "Ravi Mehta",
        "primary_color": "#0F766E",
    }
    body.update(overrides)
    return body


# --- Onboarding ---------------------------------------------------------------------------------


@covers("platform-tenants")
def test_onboarding_creates_everything_in_one_step(api, run):
    response = run(api.post, f"{P}/tenants/", _payload(), format="json")
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "ONBOARDING"
    assert body["plan"] == {"code": "BETA", "name": "Beta"}
    assert body["owner"] == {
        "email": "owner@mehta.example.com",
        "full_name": "",
        "status": "INVITATION_PENDING",
    }
    assert body["usage"] == {"staff": 0, "retailers": 0, "pending_invitations": 1}
    assert body["email"] == "accounts@mehta.example.com"
    tenant = Tenant.objects.get(slug="mehta")
    assert tenant.pan == tenant.gstin[2:12]
    with tenant_context(tenant.pk):
        assert TenantProfile.objects.count() == 1
        assert TenantBranding.objects.get().primary_color == "#0f766e"
        assert Subscription.objects.get().plan.code == "BETA"
    assert mail.outbox[-1].to == ["owner@mehta.example.com"]
    assert "mehta.localhost" in str(mail.outbox[-1].body)
    assert AuditLog.objects.filter(action="tenant.created", tenant=tenant).exists()


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"gstin": "27AAPFU0939F1ZW"}, "gstin"),  # bad check character
        ({"state_code": "24"}, "state_code"),  # GSTIN is from 27
        ({"slug": "admin"}, "slug"),
        ({"slug": "Bad Slug"}, "slug"),
        ({"pincode": "12345"}, "pincode"),
        ({"plan_code": "NOPE"}, "plan_code"),
    ],
)
def test_onboarding_validation(api, run, overrides, field):
    response = run(api.post, f"{P}/tenants/", _payload(**overrides), format="json")
    assert response.status_code == 400
    assert field in response.json()["error"]["details"]["fields"], response.json()
    assert not Tenant.objects.filter(slug=_payload(**overrides)["slug"]).exists()


def test_onboarding_refuses_duplicate_slug_or_gstin(api, run, tenant_a):
    dup_slug = run(api.post, f"{P}/tenants/", _payload(slug=tenant_a.slug), format="json")
    assert "slug" in dup_slug.json()["error"]["details"]["fields"]
    dup_gstin = run(
        api.post, f"{P}/tenants/", _payload(gstin=tenant_a.gstin, state_code="27"), format="json"
    )
    assert "gstin" in dup_gstin.json()["error"]["details"]["fields"]


@covers("platform-slug-available")
def test_slug_availability(api, tenant_a):
    assert api.get(f"{P}/tenants/slug-available/", {"slug": "fresh-co"}).json()["available"] is True
    assert (
        api.get(f"{P}/tenants/slug-available/", {"slug": tenant_a.slug}).json()["available"]
        is False
    )
    assert api.get(f"{P}/tenants/slug-available/", {"slug": "admin"}).json()["available"] is False


@covers("platform-tenant-owner-resend")
def test_owner_invitation_can_be_resent_while_onboarding(api, run):
    tenant_id = run(api.post, f"{P}/tenants/", _payload(), format="json").json()["id"]
    first = _invite_token()
    assert run(api.post, f"{P}/tenants/{tenant_id}/owner/resend-invite/").status_code == 202
    second = _invite_token()
    assert first != second
    Tenant.objects.filter(pk=tenant_id).update(status=Tenant.Status.ACTIVE)
    assert api.post(f"{P}/tenants/{tenant_id}/owner/resend-invite/").status_code == 400


# --- Access control: only super admins ----------------------------------------------------------

PLATFORM_ENDPOINTS = [
    ("get", "/tenants/"),
    ("post", "/tenants/"),
    ("get", "/dashboard/"),
    ("get", "/plans/"),
    ("get", "/feature-flags/"),
    ("get", "/tax-rates/"),
    ("post", "/tax-rates/"),
    ("get", "/cess-types/"),
    ("get", "/hsn-rate-hints/"),
    ("get", "/settings/registry/"),
    ("patch", "/settings/values/"),
    ("get", "/audit-logs/"),
]


@pytest.mark.parametrize(("method", "path"), PLATFORM_ENDPOINTS)
def test_tenant_owners_and_retailers_cannot_use_platform_endpoints(tenant_a, method, path):
    for user in (make_staff_in(tenant_a, "OWNER"), make_retailer_login(tenant_a)):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, tenant_a.pk).access}")
        response = getattr(client, method)(
            f"{P}{path}", {}, format="json", HTTP_X_FORWARDED_HOST="alpha.localhost"
        )
        assert response.status_code == 403, (user.user_type, path)
    assert getattr(APIClient(), method)(f"{P}{path}", {}, format="json").status_code == 401


def test_super_admin_token_is_refused_on_a_tenant_host(admin):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(admin, None).access}")
    assert client.get(f"{P}/tenants/", HTTP_X_FORWARDED_HOST="alpha.localhost").status_code == 401


# --- Tenants ------------------------------------------------------------------------------------


@covers("platform-tenant-detail")
def test_list_filter_and_detail(api, tenant_a, tenant_b):
    Tenant.objects.filter(pk=tenant_b.pk).update(status=Tenant.Status.SUSPENDED)
    make_staff_in(tenant_a, "OWNER")
    make_retailer_login(tenant_a)
    all_slugs = {t["slug"] for t in api.get(f"{P}/tenants/").json()["results"]}
    assert {tenant_a.slug, tenant_b.slug} <= all_slugs
    suspended = api.get(f"{P}/tenants/", {"status": "SUSPENDED"}).json()["results"]
    assert [t["slug"] for t in suspended] == [tenant_b.slug]
    assert [t["slug"] for t in api.get(f"{P}/tenants/", {"search": "alph"}).json()["results"]] == [
        tenant_a.slug
    ]
    detail = api.get(f"{P}/tenants/{tenant_a.pk}/").json()
    assert detail["usage"] == {"staff": 1, "retailers": 1, "pending_invitations": 0}
    assert detail["owner"]["status"] == "JOINED"
    assert api.get(f"{P}/tenants/00000000-0000-7000-8000-000000000000/").status_code == 404


def test_edit_is_audited_in_the_tenants_own_log(api, run, tenant_a):
    response = run(
        api.patch, f"{P}/tenants/{tenant_a.pk}/", {"legal_name": "Alpha Traders LLP"}, format="json"
    )
    assert response.json()["legal_name"] == "Alpha Traders LLP"
    entry = AuditLog.objects.get(action="tenant.updated")
    assert entry.tenant_id == tenant_a.pk
    assert entry.changes["legal_name"][1] == "Alpha Traders LLP"


def test_slug_change_needs_confirmation(api, run, tenant_a):
    refused = run(api.patch, f"{P}/tenants/{tenant_a.pk}/", {"slug": "alpha-new"}, format="json")
    assert refused.json()["error"]["code"] == "SLUG_CHANGE_NOT_CONFIRMED"
    ok = run(
        api.patch,
        f"{P}/tenants/{tenant_a.pk}/",
        {"slug": "alpha-new", "confirm_slug_change": True},
        format="json",
    )
    assert ok.json()["slug"] == "alpha-new"
    assert AuditLog.objects.filter(action="tenant.slug_changed", tenant=tenant_a).exists()


def test_gstin_change_keeps_pan_and_state_consistent(api, run, tenant_a):
    new_gstin = make_gstin(777, "24")
    bad = run(api.patch, f"{P}/tenants/{tenant_a.pk}/", {"gstin": new_gstin}, format="json")
    assert "state_code" in bad.json()["error"]["details"]["fields"]
    ok = run(
        api.patch,
        f"{P}/tenants/{tenant_a.pk}/",
        {"gstin": new_gstin, "state_code": "24"},
        format="json",
    )
    assert ok.json()["pan"] == new_gstin[2:12]


@covers("platform-tenant-suspend", "platform-tenant-reactivate")
def test_suspension_blocks_the_tenant_at_once_and_reactivation_restores(
    api, run, tenant_a, tenant_b
):
    owner = make_staff_in(tenant_a, "OWNER")
    other = make_staff_in(tenant_b, "OWNER")
    owner_client = APIClient()
    owner_client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(owner, tenant_a.pk).access}")
    other_client = APIClient()
    other_client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(other, tenant_b.pk).access}")
    assert owner_client.get("/api/v1/auth/me/").status_code == 200

    assert (
        api.post(f"{P}/tenants/{tenant_a.pk}/suspend/", {"reason": " "}, format="json").status_code
        == 400
    )
    suspended = run(
        api.post,
        f"{P}/tenants/{tenant_a.pk}/suspend/",
        {"reason": "Unpaid invoices"},
        format="json",
    )
    assert suspended.json()["status"] == "SUSPENDED"
    assert suspended.json()["suspended_reason"] == "Unpaid invoices"
    assert owner_client.get("/api/v1/auth/me/").json()["error"]["code"] == "TENANT_UNAVAILABLE"
    assert other_client.get("/api/v1/auth/me/").status_code == 200  # tenant B unaffected
    entry = AuditLog.objects.get(action="tenant.suspended")
    assert entry.tenant_id == tenant_a.pk  # the owner sees it in their own audit log

    reactivated = run(api.post, f"{P}/tenants/{tenant_a.pk}/reactivate/")
    assert reactivated.json()["status"] == "ACTIVE"
    assert owner_client.get("/api/v1/auth/me/").status_code == 200


def test_reactivating_before_the_owner_joined_returns_to_onboarding(api, run):
    tenant_id = run(api.post, f"{P}/tenants/", _payload(), format="json").json()["id"]
    run(api.post, f"{P}/tenants/{tenant_id}/suspend/", {"reason": "Duplicate"}, format="json")
    assert run(api.post, f"{P}/tenants/{tenant_id}/reactivate/").json()["status"] == "ONBOARDING"


@covers("platform-tenant-features", "platform-tenant-feature")
def test_feature_flags_per_tenant(api, run, tenant_a, tenant_b):
    assert api.get(f"{P}/tenants/{tenant_a.pk}/features/").json()["whatsapp"] is False
    response = run(
        api.put, f"{P}/tenants/{tenant_a.pk}/features/whatsapp/", {"enabled": True}, format="json"
    )
    assert response.json() == {"enabled": True}
    assert effective_features(tenant_a.pk)["whatsapp"] is True
    assert effective_features(tenant_b.pk)["whatsapp"] is False
    assert AuditLog.objects.get(action="feature.changed").tenant_id == tenant_a.pk
    run(api.put, f"{P}/tenants/{tenant_a.pk}/features/whatsapp/", {"enabled": False}, format="json")
    assert not TenantFeature.objects.unscoped().exists()  # back to default: no override row
    assert (
        api.put(
            f"{P}/tenants/{tenant_a.pk}/features/teleport/", {"enabled": True}, format="json"
        ).status_code
        == 404
    )


@covers("platform-tenant-subscription")
def test_change_plan(api, run, tenant_a):
    Plan.objects.create(code="PRO", name="Pro", price_monthly="999.00")
    with tenant_context(tenant_a.pk):
        from django.utils import timezone

        Subscription.objects.create(plan=Plan.objects.get(code="BETA"), starts_at=timezone.now())
    assert api.get(f"{P}/tenants/{tenant_a.pk}/subscription/").json()["plan"]["code"] == "BETA"
    changed = run(
        api.put, f"{P}/tenants/{tenant_a.pk}/subscription/", {"plan_code": "PRO"}, format="json"
    )
    assert changed.json()["plan"]["code"] == "PRO"
    assert current_plan(tenant_a.pk).code == "PRO"
    assert Subscription.objects.unscoped().filter(tenant=tenant_a, is_current=False).count() == 1
    assert (
        api.put(
            f"{P}/tenants/{tenant_a.pk}/subscription/", {"plan_code": "NOPE"}, format="json"
        ).status_code
        == 400
    )


@covers("platform-tenant-users")
def test_tenant_users_lists_only_that_tenant(api, tenant_a, tenant_b):
    make_staff_in(tenant_a, "OWNER", email="a@example.com")
    make_staff_in(tenant_b, "OWNER", email="b@example.com")
    emails = [
        m["user"]["email"] for m in api.get(f"{P}/tenants/{tenant_a.pk}/users/").json()["results"]
    ]
    assert emails == ["a@example.com"]


@covers("platform-dashboard")
def test_dashboard_counts(api, tenant_a, tenant_b):
    Tenant.objects.filter(pk=tenant_b.pk).update(status=Tenant.Status.SUSPENDED)
    body = api.get(f"{P}/dashboard/").json()
    assert body["active"] >= 1 and body["suspended"] == 1
    assert body["total"] == body["active"] + body["onboarding"] + body["suspended"]


# --- Plans & flags ------------------------------------------------------------------------------


@covers("platform-plans", "platform-plan-detail")
def test_plans_crud_and_default_switch(api, run):
    created = run(
        api.post,
        f"{P}/plans/",
        {
            "code": "GROWTH",
            "name": "Growth",
            "price_monthly": "1499.00",
            "max_staff": 10,
            "features": ["payments"],
        },
        format="json",
    )
    assert created.status_code == 201, created.json()
    plan_id = created.json()["id"]
    bad = api.post(
        f"{P}/plans/", {"code": "BAD", "name": "Bad", "features": ["teleport"]}, format="json"
    )
    assert "features" in bad.json()["error"]["details"]["fields"]
    run(api.patch, f"{P}/plans/{plan_id}/", {"is_default": True}, format="json")
    assert Plan.objects.get(is_default=True).code == "GROWTH"
    beta = Plan.objects.get(code="BETA")
    refuse = api.patch(f"{P}/plans/{plan_id}/", {"is_default": False}, format="json")
    assert refuse.status_code == 400
    assert not beta.is_default
    assert {p["code"] for p in api.get(f"{P}/plans/").json()} >= {"BETA", "GROWTH"}


@covers("platform-feature-flags", "platform-feature-flag-detail")
def test_flag_catalogue_default_change_applies_everywhere(api, run, tenant_a, tenant_b):
    assert len(api.get(f"{P}/feature-flags/").json()) == 11
    run(
        api.patch,
        f"{P}/feature-flags/batches/",
        {"default_enabled": True, "tenant_toggleable": True},
        format="json",
    )
    assert effective_features(tenant_a.pk)["batches"] is True
    assert effective_features(tenant_b.pk)["batches"] is True
    assert FeatureFlag.objects.get(code="batches").tenant_toggleable
    assert AuditLog.objects.get(action="feature_flag.updated").tenant_id is None


# --- Tax masters --------------------------------------------------------------------------------


@covers("platform-tax-rates", "platform-tax-rate-detail")
def test_tax_rate_master(api, run):
    rates = api.get(f"{P}/tax-rates/").json()
    assert len(rates) == 8
    created = run(api.post, f"{P}/tax-rates/", {"rate": "7.5", "label": "7.5%"}, format="json")
    assert created.status_code == 201
    dup = api.post(f"{P}/tax-rates/", {"rate": "18", "label": "dup"}, format="json")
    assert "rate" in dup.json()["error"]["details"]["fields"]
    rate_id = created.json()["id"]
    patched = run(
        api.patch, f"{P}/tax-rates/{rate_id}/", {"is_active": False, "rate": "9"}, format="json"
    )
    assert patched.json()["is_active"] is False
    assert patched.json()["rate"] == "7.500"  # the rate value itself never changes
    assert AuditLog.objects.filter(action="tax_rate.updated", tenant__isnull=True).exists()


@covers("platform-cess-types", "platform-cess-type-detail")
def test_cess_types(api, run):
    created = run(
        api.post,
        f"{P}/cess-types/",
        {"code": "COMP_CESS", "name": "Compensation cess"},
        format="json",
    )
    assert created.status_code == 201
    updated = run(
        api.patch, f"{P}/cess-types/{created.json()['id']}/", {"is_active": False}, format="json"
    )
    assert updated.json()["is_active"] is False


@covers("platform-hsn-hints", "platform-hsn-hint-detail", "platform-hsn-hints-import")
def test_hsn_hints_crud_and_import(api, run):
    created = run(
        api.post,
        f"{P}/hsn-rate-hints/",
        {"hsn_prefix": "3004", "gst_rate": "5", "effective_from": "2025-09-22"},
        format="json",
    )
    assert created.status_code == 201, created.json()
    not_in_master = api.post(
        f"{P}/hsn-rate-hints/",
        {"hsn_prefix": "3005", "gst_rate": "7", "effective_from": "2025-09-22"},
        format="json",
    )
    assert "gst_rate" in not_in_master.json()["error"]["details"]["fields"]
    hint_id = created.json()["id"]
    assert (
        run(api.patch, f"{P}/hsn-rate-hints/{hint_id}/", {"gst_rate": "18"}, format="json").json()[
            "gst_rate"
        ]
        == "18.000"
    )

    good = (
        b"hsn_prefix,gst_rate,effective_from,description\n"
        b"3004,5,2025-09-22,Medicines\n"
        b"8471,18,2025-09-22,Computers\n"
    )
    imported = run(
        api.post,
        f"{P}/hsn-rate-hints/import/",
        {"file": SimpleUploadedFile("h.csv", good, "text/csv")},
        format="multipart",
    )
    assert imported.json() == {"created": 1, "updated": 1}
    bad = (
        b"hsn_prefix,gst_rate,effective_from\n"
        b"99,5,2025-01-01\n"
        b"1234,7,2025-01-01\n"
        b"abc,5,2025-01-01\n"
    )
    refused = api.post(
        f"{P}/hsn-rate-hints/import/",
        {"file": SimpleUploadedFile("h.csv", bad, "text/csv")},
        format="multipart",
    )
    errors = refused.json()["error"]["details"]["fields"]["file"]
    assert any("Row 3" in e for e in errors) and any("Row 4" in e for e in errors)
    assert not HsnRateHint.objects.filter(hsn_prefix="99").exists()  # all or nothing

    assert run(api.delete, f"{P}/hsn-rate-hints/{hint_id}/").status_code == 204
    assert (
        api.get(f"{P}/hsn-rate-hints/", {"prefix": "84"}).json()["results"][0]["hsn_prefix"]
        == "8471"
    )


# --- Platform settings & audit ------------------------------------------------------------------


@covers("platform-settings-registry", "platform-settings-values")
def test_platform_settings(api, run):
    rows = api.get(f"{P}/settings/registry/").json()
    assert len(rows) == 26  # + the AI limits (ADR-058, 059)
    row = next(r for r in rows if r["key"] == "platform.login_lockout_minutes")
    assert (row["value"], row["default"], row["is_default"], row["can_edit"]) == (
        15,
        15,
        True,
        True,
    )
    updated = run(
        api.patch,
        f"{P}/settings/values/",
        {"values": {"platform.login_lockout_minutes": 20}},
        format="json",
    )
    row = next(r for r in updated.json() if r["key"] == "platform.login_lockout_minutes")
    assert (row["value"], row["is_default"]) == (20, False)
    bad = api.patch(
        f"{P}/settings/values/",
        {"values": {"platform.login_lockout_minutes": 99999}},
        format="json",
    )
    assert "platform.login_lockout_minutes" in bad.json()["error"]["details"]["fields"]


@covers("platform-audit-logs")
def test_platform_audit_log_sees_all_tenants_and_filters(api, run, tenant_a, tenant_b):
    run(api.post, f"{P}/tenants/{tenant_a.pk}/suspend/", {"reason": "x"}, format="json")
    run(api.post, f"{P}/tenants/{tenant_b.pk}/suspend/", {"reason": "y"}, format="json")
    run(api.post, f"{P}/tax-rates/", {"rate": "7.5", "label": "7.5%"}, format="json")
    actions = [e["action"] for e in api.get(f"{P}/audit-logs/").json()["results"]]
    assert actions.count("tenant.suspended") == 2 and "tax_rate.created" in actions
    only_a = api.get(f"{P}/audit-logs/", {"tenant_id": str(tenant_a.pk)}).json()["results"]
    assert {e["tenant"]["id"] for e in only_a} == {str(tenant_a.pk)}
    assert (
        api.get(f"{P}/audit-logs/", {"action": "tax_rate."}).json()["results"][0]["actor"]["email"]
        == "root@platform.example.com"
    )


def test_public_states_need_no_sign_in():
    states = APIClient().get("/api/v1/public/states/").json()
    assert len(states) == 37  # 39 codes, 2 legacy ones inactive
    assert {"code": "27", "name": "Maharashtra", "is_union_territory": False} in states


def test_onboarded_tenant_owner_joins_and_tenant_becomes_active(api, run):
    tenant_id = run(api.post, f"{P}/tenants/", _payload(), format="json").json()["id"]
    token = _invite_token()
    accepted = APIClient().post(
        "/api/v1/auth/invitations/accept/",
        {"token": token, "full_name": "Ravi Mehta", "password": "a-new-strong-passphrase"},
        format="json",
        HTTP_X_FORWARDED_HOST="mehta.localhost",
    )
    assert accepted.json()["status"] == "authenticated", accepted.json()
    assert Tenant.objects.get(pk=tenant_id).status == Tenant.Status.ACTIVE
    assert Membership.objects.unscoped().get(tenant_id=tenant_id).role.code == "OWNER"
    assert Invitation.objects.unscoped().get(tenant_id=tenant_id).status == "ACCEPTED"
    assert TaxRate.objects.count() == 8
