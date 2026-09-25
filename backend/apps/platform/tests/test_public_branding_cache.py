"""The sign-in page's branding is cached per tenant (Redis) and every change that affects it is
visible on the very next request (invalidation on commit, never a timeout)."""

import io
import re

import pytest
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in, make_super_admin
from apps.accounts.tokens import issue_tokens
from apps.platform.models import Tenant, TenantBranding, TenantProfile
from apps.platform.tests.factories import make_gstin
from common.storage import InMemoryStorage
from common.tenancy import tenant_context

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


@pytest.fixture
def admin_api():
    client = APIClient()
    token = issue_tokens(make_super_admin("root@platform.example.com"), None).access
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = "admin.localhost"
    return client


@pytest.fixture
def owner(tenant_a):
    user = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    with tenant_context(tenant_a.pk):
        TenantProfile.objects.create()
        TenantBranding.objects.create(display_name="Alpha", primary_color="#2f5bea")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, tenant_a.pk).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant_a.slug}.localhost"
    return client


def branding(slug):
    return APIClient().get(f"/api/v1/public/tenants/{slug}/branding/")


def test_repeat_requests_are_served_from_the_cache(owner, tenant_a):
    assert branding(tenant_a.slug).json()["display_name"] == "Alpha"
    with CaptureQueriesContext(connection) as queries:
        assert branding(tenant_a.slug).json()["display_name"] == "Alpha"
    # Only the request transaction's savepoint statements; no data is read.
    reads = [q["sql"] for q in queries.captured_queries if "SAVEPOINT" not in q["sql"]]
    assert reads == []


def test_unknown_addresses_are_not_cached():
    assert branding("nobody").status_code == 404
    assert cache.get("public_branding:nobody") is None


def test_a_status_change_is_visible_on_the_very_next_request(owner, tenant_a, admin_api, run):
    assert branding(tenant_a.slug).json()["available"] is True  # now cached

    suspend = f"/api/v1/platform/tenants/{tenant_a.pk}/suspend/"
    assert run(admin_api.post, suspend, {"reason": "Unpaid"}, format="json").status_code == 200
    assert branding(tenant_a.slug).json()["available"] is False

    reactivate = f"/api/v1/platform/tenants/{tenant_a.pk}/reactivate/"
    assert run(admin_api.post, reactivate).status_code == 200
    assert branding(tenant_a.slug).json()["available"] is True


def test_the_owner_joining_opens_sign_in_on_the_next_request(admin_api, run):
    body = {
        "name": "Mehta Wholesale",
        "legal_name": "Mehta Wholesale Private Limited",
        "gstin": make_gstin(4242, "27"),
        "state_code": "27",
        "address_line1": "Plot 7, MIDC",
        "city": "Nashik",
        "pincode": "422007",
        "email": "accounts@mehta.example.com",
        "phone": "02532345678",
        "slug": "mehta",
        "owner_email": "owner@mehta.example.com",
    }
    assert run(admin_api.post, "/api/v1/platform/tenants/", body, format="json").status_code == 201
    assert branding("mehta").json()["available"] is False  # onboarding, now cached

    token = re.search(r"/invite/(\S+)", str(mail.outbox[-1].body)).group(1)  # type: ignore[union-attr]
    accepted = run(
        APIClient().post,
        "/api/v1/auth/invitations/accept/",
        {"token": token, "full_name": "Ravi Mehta", "password": "a-new-strong-passphrase"},
        format="json",
        HTTP_X_FORWARDED_HOST="mehta.localhost",
    )
    assert accepted.json()["status"] == "authenticated"
    assert branding("mehta").json()["available"] is True


def test_branding_changes_are_visible_on_the_next_request(owner, tenant_a, run):
    branding(tenant_a.slug)
    run(
        owner.patch,
        "/api/v1/settings/branding/",
        {"display_name": "Alpha Wholesale", "primary_color": "#C2410C"},
        format="json",
    )
    body = branding(tenant_a.slug).json()
    assert (body["display_name"], body["primary_color"]) == ("Alpha Wholesale", "#c2410c")


def test_logo_upload_and_removal_are_visible_on_the_next_request(owner, tenant_a, run):
    assert branding(tenant_a.slug).json()["logo_url"] is None
    image = io.BytesIO()
    Image.new("RGB", (64, 64), (47, 91, 234)).save(image, format="PNG")
    upload = SimpleUploadedFile("logo.png", image.getvalue(), content_type="image/png")
    run(owner.post, "/api/v1/settings/branding/assets/logo/", {"file": upload}, format="multipart")
    assert branding(tenant_a.slug).json()["logo_url"] is not None
    run(owner.delete, "/api/v1/settings/branding/assets/logo/")
    assert branding(tenant_a.slug).json()["logo_url"] is None


def test_business_name_change_drops_the_cached_entry(owner, tenant_a, run):
    branding(tenant_a.slug)
    assert cache.get(f"public_branding:{tenant_a.slug}") is not None
    run(owner.patch, "/api/v1/settings/business/", {"name": "Alpha Traders"}, format="json")
    assert cache.get(f"public_branding:{tenant_a.slug}") is None


def test_web_address_change_moves_the_page_at_once(owner, tenant_a, admin_api, run):
    old = tenant_a.slug
    assert branding(old).status_code == 200  # cached under the old address
    response = run(
        admin_api.patch,
        f"/api/v1/platform/tenants/{tenant_a.pk}/",
        {"slug": "alpha-new", "confirm_slug_change": True},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert branding(old).status_code == 404
    assert branding("alpha-new").json()["slug"] == "alpha-new"
    assert Tenant.objects.get(pk=tenant_a.pk).slug == "alpha-new"
