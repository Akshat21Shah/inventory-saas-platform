"""Task 5.13: after the first invoice the GST identity (GSTIN, legal name, state) is read-only for
the distributor and in the normal super admin edit; a separate super admin action with a reason
changes it, audited, and issued invoices keep their snapshot."""

from decimal import Decimal as D

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in, make_super_admin
from apps.accounts.tokens import issue_tokens
from apps.audit.models import AuditLog
from apps.billing.models import Invoice
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import add_stock, client_for, make_shop
from apps.platform.models import Tenant, TenantProfile
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
def api():
    client = APIClient()
    admin = make_super_admin("root@platform.example.com")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(admin, None).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = "admin.localhost"
    return client


@pytest.fixture
def owner(tenant_a):
    user = make_staff_in(tenant_a, "OWNER")
    with tenant_context(tenant_a.pk):
        TenantProfile.objects.get_or_create()
    return user


def _invoice(tenant, owner):
    shop = make_shop(tenant)
    a = make_product(tenant, "A", base_price=D("100"))
    add_stock(tenant, a, "5")
    return ship_invoice(tenant, shop, owner, (a, "1"))


def test_before_the_first_invoice_the_distributor_may_change_it(tenant_a, owner):
    c = client_for(tenant_a, owner)
    assert c.get("/api/v1/settings/business/").json()["gst_identity_locked"] is False
    changed = c.patch("/api/v1/settings/business/", {"legal_name": "Alpha LLP"}, format="json")
    assert changed.status_code == 200 and changed.json()["legal_name"] == "Alpha LLP"


def test_after_it_only_the_super_admin_action_can(
    tenant_a, owner, api, django_capture_on_commit_callbacks
):
    invoice = _invoice(tenant_a, owner)
    c = client_for(tenant_a, owner)
    assert c.get("/api/v1/settings/business/").json()["gst_identity_locked"] is True
    for body in ({"legal_name": "Other LLP"}, {"gstin": make_gstin(901)}, {"state_code": "24"}):
        refused = c.patch("/api/v1/settings/business/", body, format="json")
        assert refused.status_code == 409, body
        assert refused.json()["error"]["code"] == "GST_IDENTITY_LOCKED"
    assert (
        c.patch("/api/v1/settings/business/", {"city": "Nashik"}, format="json").status_code == 200
    )
    assert api.get(f"{P}/tenants/{tenant_a.pk}/").json()["gst_identity_locked"] is True
    edit = api.patch(f"{P}/tenants/{tenant_a.pk}/", {"legal_name": "Other LLP"}, format="json")
    assert edit.status_code == 409

    no_reason = api.post(
        f"{P}/tenants/{tenant_a.pk}/gst-identity/", {"legal_name": "Other LLP", "reason": " "},
        format="json",
    )  # fmt: skip
    assert no_reason.status_code == 400
    new_gstin = make_gstin(902)
    with django_capture_on_commit_callbacks(execute=True):
        done = api.post(
            f"{P}/tenants/{tenant_a.pk}/gst-identity/",
            {
                "legal_name": "Alpha Traders LLP",
                "gstin": new_gstin,
                "reason": "Constitution changed",
            },
            format="json",
        )
    assert done.status_code == 200, done.json()
    tenant = Tenant.objects.get(pk=tenant_a.pk)
    assert (tenant.legal_name, tenant.gstin, tenant.pan) == (
        "Alpha Traders LLP",
        new_gstin,
        new_gstin[2:12],
    )
    entry = AuditLog.objects.get(action="tenant.gst_identity_changed")
    assert entry.metadata["reason"] == "Constitution changed" and "gstin" in entry.changes
    with tenant_context(tenant_a.pk):
        kept = Invoice.objects.get(pk=invoice.pk)
    assert kept.seller["gstin"] == tenant_a.gstin  # the issued invoice keeps its snapshot


@covers("platform-tenant-gst-identity")
def test_only_super_admins_change_it(tenant_a, owner):
    c = client_for(tenant_a, owner)
    body = {"legal_name": "X", "reason": "y"}
    assert c.post(f"{P}/tenants/{tenant_a.pk}/gst-identity/", body, format="json").status_code in (
        401,
        403,
    )
