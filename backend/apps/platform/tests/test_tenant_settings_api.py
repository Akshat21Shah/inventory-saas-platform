"""Distributor settings, branding, assets, flags and audit log (spec 5.3, 5.16, PLAN §3.4)."""

import io

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in, make_super_admin
from apps.accounts.tokens import issue_tokens
from apps.audit.models import AuditLog
from apps.platform import tenant_services
from apps.platform.models import FeatureFlag, TenantBranding, TenantProfile
from apps.platform.tests.factories import make_gstin
from common.storage import InMemoryStorage
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    InMemoryStorage.objects.clear()
    yield
    cache.clear()
    InMemoryStorage.objects.clear()


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    def _run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return _run


def _client(user, tenant):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, tenant.pk).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant.slug}.localhost"
    return client


@pytest.fixture
def owner(tenant_a):
    user = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    with tenant_context(tenant_a.pk):
        TenantProfile.objects.create()
        TenantBranding.objects.create(display_name="Alpha")
    return _client(user, tenant_a)


@pytest.fixture
def sales(tenant_a):
    return _client(make_staff_in(tenant_a, "SALES"), tenant_a)


def _png(size=(64, 64), fmt="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", size, (47, 91, 234)).save(buffer, format=fmt)
    return buffer.getvalue()


def _upload(content, name="logo.png", content_type="image/png"):
    return {"file": SimpleUploadedFile(name, content, content_type)}


# --- Business & bank details --------------------------------------------------------------------


@covers("settings-business")
def test_business_details_read_by_staff_changed_by_owner(tenant_a, tenant_b, owner, sales, run):
    body = sales.get("/api/v1/settings/business/").json()
    assert body["gstin"] == tenant_a.gstin
    assert body["slug"] == tenant_a.slug
    assert (
        sales.patch("/api/v1/settings/business/", {"legal_name": "X"}, format="json").status_code
        == 403
    )

    response = run(
        owner.patch,
        "/api/v1/settings/business/",
        {
            "legal_name": "Alpha Traders LLP",
            "invoice_terms": "Pay within 30 days.",
            "slug": "hijack",
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["legal_name"] == "Alpha Traders LLP"
    assert response.json()["invoice_terms"] == "Pay within 30 days."
    assert response.json()["slug"] == tenant_a.slug  # read-only for distributors (ADR-030)
    tenant_b.refresh_from_db()
    assert tenant_b.legal_name != "Alpha Traders LLP"
    assert set(AuditLog.objects.filter(tenant=tenant_a).values_list("action", flat=True)) >= {
        "tenant.updated",
        "settings.business_profile_changed",
    }


def test_gstin_change_must_match_state(owner, run):
    other_state = make_gstin(99, "24")
    bad = run(owner.patch, "/api/v1/settings/business/", {"gstin": other_state}, format="json")
    assert "state_code" in bad.json()["error"]["details"]["fields"]
    ok = run(
        owner.patch,
        "/api/v1/settings/business/",
        {"gstin": other_state, "state_code": "24"},
        format="json",
    )
    assert ok.json()["pan"] == other_state[2:12]


@covers("settings-bank-details")
def test_bank_details_are_encrypted_masked_and_audited_masked(tenant_a, owner, sales, run):
    assert sales.get("/api/v1/settings/bank-details/").status_code == 403
    bad = owner.put("/api/v1/settings/bank-details/", {"bank_ifsc": "HDFC1234567"}, format="json")
    assert "bank_ifsc" in bad.json()["error"]["details"]["fields"]
    response = run(
        owner.put,
        "/api/v1/settings/bank-details/",
        {
            "bank_account_name": "Alpha Traders",
            "bank_account_number": "50100012345678",
            "bank_ifsc": "hdfc0001234",
            "upi_id": "alpha@okhdfc",
        },
        format="json",
    )
    body = response.json()
    assert body["bank_account_number_masked"] == "••••5678"
    assert "bank_account_number" not in body
    assert body["bank_ifsc"] == "HDFC0001234"
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT bank_account_number FROM platform_tenantprofile WHERE tenant_id = %s",
            [tenant_a.pk],
        )
        assert "50100012345678" not in cursor.fetchone()[0]
    entry = AuditLog.objects.get(action="settings.bank_details_changed")
    assert entry.changes["bank_account_number"] == ["", "••••5678"]
    from apps.platform.api.tenant_views import BankDetailsView

    assert BankDetailsView.impersonation_blocked is True


# --- Commercial settings (registry) -------------------------------------------------------------


@covers("settings-registry", "settings-values", "settings-value-reset")
def test_registry_settings_per_tenant_with_per_key_permission(
    tenant_a, tenant_b, owner, sales, run
):
    rows = sales.get("/api/v1/settings/registry/").json()
    assert len(rows) == 42
    assert not any(r["can_edit"] for r in rows)
    assert all(r["can_edit"] for r in owner.get("/api/v1/settings/registry/").json())
    denied = sales.patch(
        "/api/v1/settings/values/", {"values": {"orders.acceptance_mode": "AUTO"}}, format="json"
    )
    assert denied.status_code == 403

    updated = run(
        owner.patch,
        "/api/v1/settings/values/",
        {"values": {"orders.acceptance_mode": "AUTO", "orders.min_order_value": "2500"}},
        format="json",
    )
    row = {r["key"]: r for r in updated.json()}
    assert (
        row["orders.acceptance_mode"]["value"] == "AUTO"
        and not row["orders.acceptance_mode"]["is_default"]
    )
    assert row["orders.min_order_value"]["value"] == "2500.00"
    assert row["orders.min_order_value_basis"]["depends_on"] == {
        "key": "orders.min_order_value",
        "equals": None,
        "not_null": True,
    }

    owner_b = _client(make_staff_in(tenant_b, "OWNER"), tenant_b)
    b_rows = {r["key"]: r for r in owner_b.get("/api/v1/settings/registry/").json()}
    assert b_rows["orders.acceptance_mode"]["value"] == "MANUAL"  # tenant B untouched

    reset = run(owner.delete, "/api/v1/settings/values/orders.acceptance_mode/")
    assert {r["key"]: r for r in reset.json()}["orders.acceptance_mode"]["is_default"] is True
    invalid = owner.patch(
        "/api/v1/settings/values/",
        {"values": {"tax.registration_type": "COMPOSITION"}},
        format="json",
    )
    assert "tax.registration_type" in invalid.json()["error"]["details"]["fields"]


# --- Branding & assets --------------------------------------------------------------------------


@covers("settings-branding")
def test_branding_read_by_staff_changed_with_branding_permission(tenant_a, owner, sales, run):
    manager = _client(make_staff_in(tenant_a, "MANAGER"), tenant_a)
    assert sales.get("/api/v1/settings/branding/").json()["display_name"] == "Alpha"
    assert (
        manager.patch(
            "/api/v1/settings/branding/", {"primary_color": "#123456"}, format="json"
        ).status_code
        == 403
    )
    bad = owner.patch("/api/v1/settings/branding/", {"primary_color": "blue"}, format="json")
    assert "primary_color" in bad.json()["error"]["details"]["fields"]
    ok = run(
        owner.patch,
        "/api/v1/settings/branding/",
        {"primary_color": "#0F766E", "display_name": "Alpha Wholesale"},
        format="json",
    )
    assert ok.json()["primary_color"] == "#0f766e"
    assert AuditLog.objects.filter(action="settings.branding_changed", tenant=tenant_a).exists()


@covers("settings-branding-asset", "public-tenant-asset")
def test_logo_upload_is_validated_stored_per_tenant_and_served_by_redirect(
    tenant_a, tenant_b, owner, run
):
    response = run(
        owner.post, "/api/v1/settings/branding/assets/logo/", _upload(_png()), format="multipart"
    )
    assert response.status_code == 201, response.json()
    first_url = response.json()["logo_url"]
    assert first_url.startswith(f"/api/v1/public/tenants/{tenant_a.slug}/assets/logo/?v=")
    [key] = list(InMemoryStorage.objects)
    assert key.startswith(f"tenants/{tenant_a.pk}/branding/logo/") and key.endswith(".png")

    redirect = APIClient().get(f"/api/v1/public/tenants/{tenant_a.slug}/assets/logo/")
    assert redirect.status_code == 302 and key in redirect["Location"]
    assert (
        APIClient().get(f"/api/v1/public/tenants/{tenant_b.slug}/assets/logo/").status_code == 404
    )

    replaced = run(
        owner.post,
        "/api/v1/settings/branding/assets/logo/",
        _upload(_png(fmt="WEBP"), "l.webp", "image/webp"),
        format="multipart",
    )
    assert replaced.status_code == 201
    [new_key] = list(InMemoryStorage.objects)  # the old file was deleted after commit
    assert new_key != key and new_key.endswith(".webp")
    assert replaced.json()["logo_url"] != first_url  # a new version: no stale browser cache

    removed = run(owner.delete, "/api/v1/settings/branding/assets/logo/")
    assert removed.json()["logo_url"] is None
    assert InMemoryStorage.objects == {}


@pytest.mark.parametrize(
    ("content", "name"),
    [
        (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "logo.svg"),
        (b"%PDF-1.4 not an image", "logo.png"),  # the name lies; the content decides
        (b"GIF89a" + b"\x00" * 20, "logo.gif"),
    ],
)
def test_unsafe_or_unsupported_uploads_are_refused(owner, content, name):
    response = owner.post(
        "/api/v1/settings/branding/assets/logo/", _upload(content, name), format="multipart"
    )
    assert "file" in response.json()["error"]["details"]["fields"]
    assert InMemoryStorage.objects == {}


def test_oversized_image_is_refused(owner):
    big = _png(size=(5000, 10))
    response = owner.post(
        "/api/v1/settings/branding/assets/logo/", _upload(big), format="multipart"
    )
    assert "file" in response.json()["error"]["details"]["fields"]


@covers("settings-signatory-image")
def test_signatory_image_is_private(tenant_a, owner, sales, run):
    manager = _client(make_staff_in(tenant_a, "MANAGER"), tenant_a)
    assert (
        manager.post(
            "/api/v1/settings/branding/assets/signatory/", _upload(_png()), format="multipart"
        ).status_code
        == 403
    )
    assert (
        run(
            owner.post,
            "/api/v1/settings/branding/assets/signatory/",
            _upload(_png()),
            format="multipart",
        ).status_code
        == 201
    )
    assert owner.get("/api/v1/settings/business/").json()["has_signatory_image"] is True
    assert owner.get("/api/v1/settings/signatory-image/").status_code == 302
    assert sales.get("/api/v1/settings/signatory-image/").status_code == 403
    assert (
        APIClient().get(f"/api/v1/public/tenants/{tenant_a.slug}/assets/signatory/").status_code
        == 404
    )


@covers("public-tenant-branding")
def test_public_branding_for_pre_login_pages(tenant_a, tenant_b, owner, run):
    run(owner.patch, "/api/v1/settings/branding/", {"primary_color": "#0f766e"}, format="json")
    body = APIClient().get(f"/api/v1/public/tenants/{tenant_a.slug}/branding/").json()
    assert body == {
        "slug": tenant_a.slug,
        "display_name": "Alpha",
        "primary_color": "#0f766e",
        "available": True,
        "logo_url": None,
        "favicon_url": None,
        "app_icon_url": None,
    }
    other = APIClient().get(f"/api/v1/public/tenants/{tenant_b.slug}/branding/").json()
    assert other["primary_color"] != "#0f766e" and other["slug"] == tenant_b.slug
    assert APIClient().get("/api/v1/public/tenants/nobody/branding/").status_code == 404


# --- Feature flags ------------------------------------------------------------------------------


@covers("settings-features", "settings-feature-toggle")
def test_owner_toggles_only_tenant_toggleable_modules(tenant_a, tenant_b, owner, sales, run):
    flags = {f["code"]: f for f in sales.get("/api/v1/settings/features/").json()}
    assert len(flags) == 8 and flags["batches"]["enabled"] is False
    refused = owner.put("/api/v1/settings/features/batches/", {"enabled": True}, format="json")
    assert "enabled" in refused.json()["error"]["details"]["fields"]
    FeatureFlag.objects.filter(code="batches").update(tenant_toggleable=True)
    assert (
        sales.put(
            "/api/v1/settings/features/batches/", {"enabled": True}, format="json"
        ).status_code
        == 403
    )
    ok = run(owner.put, "/api/v1/settings/features/batches/", {"enabled": True}, format="json")
    assert ok.json()["enabled"] is True
    owner_b = _client(make_staff_in(tenant_b, "OWNER"), tenant_b)
    assert {f["code"]: f for f in owner_b.get("/api/v1/settings/features/").json()}["batches"][
        "enabled"
    ] is False


# --- Audit log ----------------------------------------------------------------------------------


@covers("audit-logs")
def test_owner_sees_own_tenants_trail_including_platform_actions(tenant_a, tenant_b, owner, run):
    admin = make_super_admin()
    run(tenant_services.set_tenant_feature, tenant_a.pk, "whatsapp", True, by=admin)
    run(tenant_services.set_tenant_feature, tenant_b.pk, "whatsapp", True, by=admin)
    run(owner.patch, "/api/v1/settings/branding/", {"display_name": "Alpha Co"}, format="json")
    entries = owner.get("/api/v1/audit-logs/").json()["results"]
    assert {e["action"] for e in entries} == {"feature.changed", "settings.branding_changed"}
    assert all(e["tenant"]["id"] == str(tenant_a.pk) for e in entries)
    filtered = owner.get(
        "/api/v1/audit-logs/", {"action": "feature.", "tenant_id": str(tenant_b.pk)}
    ).json()["results"]
    assert [e["tenant"]["id"] for e in filtered] == [
        str(tenant_a.pk)
    ]  # tenant_id filter is ignored
    manager = _client(make_staff_in(tenant_a, "MANAGER"), tenant_a)
    assert manager.get("/api/v1/audit-logs/").status_code == 403
