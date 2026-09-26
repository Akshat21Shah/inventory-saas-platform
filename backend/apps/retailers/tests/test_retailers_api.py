"""Retailers (spec 5.5, PLAN §3.6): profile, GSTIN, credit, hold, sign-in on hold (ADR-036),
sales visibility, welcome message, soft delete, and tenant isolation for every route."""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.adapters.sms import MockSmsSender
from apps.accounts.models import User
from apps.accounts.tests.factories import make_staff_in
from apps.accounts.tokens import issue_tokens
from apps.audit.models import AuditLog
from apps.platform.models import TenantSetting
from apps.retailers.models import Retailer, RetailerAddress
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    MockSmsSender.outbox.clear()
    yield
    cache.clear()
    MockSmsSender.outbox.clear()


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    def _run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return _run


def _client(tenant, role="OWNER", user=None):
    user = user or make_staff_in(tenant, role)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, tenant.pk).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant.slug}.localhost"
    return client


@pytest.fixture
def owner(tenant_a):
    return _client(tenant_a)


def _create(client, run=None, **overrides):
    body = {"shop_name": "Ganesh Kirana", "mobile": "98765 43210", "owner_name": "Ganesh"}
    body.update(overrides)
    post = (
        (lambda: run(client.post, f"{API}/retailers/", body, format="json"))
        if run
        else (lambda: client.post(f"{API}/retailers/", body, format="json"))
    )
    return post()


def _fields(response):
    assert response.status_code == 400, response.json()
    return response.json()["error"]["details"]["fields"]


@covers("retailers", "retailer-detail")
def test_create_gives_a_code_a_login_and_a_welcome_message(owner, tenant_a, run):
    response = _create(
        owner,
        run,
        billing_address={
            "line1": "12 Station Road",
            "city": "Pune",
            "pincode": "411001",
            "state_code": "27",
        },
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert (body["code"], body["mobile"], body["state_code"], body["gstin"]) == (
        "R-00001",
        "+919876543210",
        "27",
        None,
    )
    assert body["payment_terms_days"] == 30  # invoicing.default_payment_terms_days
    assert body["addresses"][0]["kind"] == "BILLING" and body["addresses"][0]["is_default"]
    login = User.objects.get(phone="+919876543210", tenant=tenant_a)
    assert login.user_type == "RETAILER" and login.full_name == "Ganesh"
    [sms] = MockSmsSender.outbox
    assert sms.template == "retailer_welcome" and "alpha.localhost" in sms.text
    assert _create(owner).json()["error"]["details"]["fields"]["mobile"] == [
        "Another shop already uses this mobile number."
    ]
    second = _create(owner, mobile="9876543211", shop_name="Two").json()
    assert second["code"] == "R-00002"
    assert AuditLog.objects.filter(action="retailer.created").count() == 2


def test_gstin_rules_for_shops(owner):
    fields = _fields(_create(owner, gstin="27AAGFK7315R1ZA"))
    assert "Check for mix-ups like O/0, I/1 or S/5." in fields["gstin"][0]
    fields = _fields(_create(owner, gstin="27AAGFK7315R1ZP", state_code="29"))
    assert "must match the first 2 digits of the GSTIN (27)" in fields["state"][0]
    registered = _create(owner, gstin="27 aagfk 7315r 1zp").json()
    assert (registered["gstin"], registered["pan"], registered["state_code"]) == (
        "27AAGFK7315R1ZP",
        "AAGFK7315R",
        "27",
    )
    duplicate = _create(owner, mobile="9876500009", gstin="27AAGFK7315R1ZP")
    assert _fields(duplicate)["gstin"] == ["Another shop already has this GSTIN."]
    unregistered = _create(owner, mobile="9876500010", state_code="24").json()
    assert (unregistered["gstin"], unregistered["state_code"]) == (None, "24")


@covers("retailer-credit", "retailer-block", "retailer-unblock")
def test_credit_needs_its_own_permission_and_hold_is_audited(owner, tenant_a):
    retailer = _create(owner).json()
    url = f"{API}/retailers/{retailer['id']}/"
    sales = _client(tenant_a, "SALES")  # retailers.manage, not credit.manage
    denied = sales.patch(
        f"{url}credit/", {"credit_limit": "5000", "payment_terms_days": 15}, format="json"
    )
    assert denied.status_code == 403
    done = owner.patch(
        f"{url}credit/", {"credit_limit": "0", "payment_terms_days": 15}, format="json"
    ).json()
    assert (done["credit_limit"], done["payment_terms_days"]) == ("0.00", 15)
    assert AuditLog.objects.get(action="retailer.credit_changed").changes == {
        "credit_limit": [None, "0.00"],
        "payment_terms_days": [30, 15],
    }

    assert "reason" in _fields(owner.post(f"{url}block/", {"reason": ""}, format="json"))
    held = owner.post(f"{url}block/", {"reason": "Payment overdue"}, format="json").json()
    assert (held["status"], held["blocked_reason"]) == ("BLOCKED", "Payment overdue")
    assert owner.post(f"{url}unblock/").json()["status"] == "ACTIVE"
    assert {"retailer.blocked", "retailer.unblocked"} <= set(
        AuditLog.objects.values_list("action", flat=True)
    )


def _shop_session(tenant, phone="+919876543210"):
    user = User.objects.get(tenant=tenant, phone=phone)
    return _client(tenant, user=user)


def test_shops_on_hold_sign_in_by_default_and_are_refused_when_turned_off(owner, tenant_a):
    retailer = _create(owner).json()
    shop = _shop_session(tenant_a)
    owner.post(f"{API}/retailers/{retailer['id']}/block/", {"reason": "Overdue"}, format="json")
    me = shop.get(f"{API}/auth/me/")
    assert me.status_code == 200 and me.json()["retailer"]["on_hold"] is True

    with tenant_context(tenant_a.pk):
        TenantSetting.objects.create(key="retailers.blocked_can_sign_in", value=False)
    cache.clear()
    refused = shop.get(f"{API}/auth/me/")
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "RETAILER_ON_HOLD"
    assert refused.json()["error"]["message"] == (
        "Your account is on hold. Please contact your distributor."
    )


@covers("retailer-resend-welcome", "retailer-addresses", "retailer-address-detail")
def test_addresses_welcome_and_delete_ends_the_login(owner, tenant_a, run):
    retailer = _create(owner).json()
    base = f"{API}/retailers/{retailer['id']}/"
    shipping = owner.post(
        f"{base}addresses/",
        {
            "kind": "SHIPPING",
            "line1": "Godown 4",
            "city": "Hadapsar",
            "pincode": "411028",
            "state_code": "27",
        },
        format="json",
    )
    assert shipping.status_code == 201 and shipping.json()["is_default"] is True  # first one
    second = owner.post(
        f"{base}addresses/",
        {
            "kind": "SHIPPING",
            "line1": "Shop 2",
            "city": "Pune",
            "pincode": "411001",
            "state_code": "27",
            "is_default": True,
        },
        format="json",
    ).json()
    with tenant_context(tenant_a.pk):
        defaults = RetailerAddress.objects.filter(kind="SHIPPING", is_default=True)
        assert [a.line1 for a in defaults] == ["Shop 2"]
    assert "pincode" in _fields(
        owner.patch(
            f"{base}addresses/{second['id']}/",
            {"kind": "SHIPPING", "line1": "X", "city": "Y", "pincode": "0110", "state_code": "27"},
            format="json",
        )
    )
    assert owner.delete(f"{base}addresses/{second['id']}/").status_code == 204

    assert run(owner.post, f"{base}resend-welcome/").status_code == 202
    assert MockSmsSender.outbox[-1].template == "retailer_welcome"

    shop = _shop_session(tenant_a)
    assert shop.get(f"{API}/auth/me/").status_code == 200
    assert owner.delete(base).status_code == 204
    assert shop.get(f"{API}/auth/me/").status_code == 401
    assert owner.get(base).status_code == 404
    again = _create(owner).json()  # the number is free again; the login moves to the new shop
    assert again["code"] == "R-00002"
    assert User.objects.get(phone="+919876543210", tenant=tenant_a).is_active


def test_changing_the_mobile_moves_the_sign_in(owner, tenant_a):
    retailer = _create(owner).json()
    owner.patch(f"{API}/retailers/{retailer['id']}/", {"mobile": "9123456789"}, format="json")
    assert User.objects.filter(phone="+919123456789", tenant=tenant_a).exists()
    assert not User.objects.filter(phone="+919876543210", tenant=tenant_a).exists()


@covers("retailers-bulk", "retailers-salespeople")
def test_sales_staff_may_be_limited_to_their_own_shops(owner, tenant_a):
    salesperson = make_staff_in(tenant_a, "SALES")
    mine = _create(owner, salesperson=str(salesperson.pk)).json()
    other = _create(owner, mobile="9876500002", shop_name="Other").json()
    sales = _client(tenant_a, user=salesperson)
    assert len(sales.get(f"{API}/retailers/").json()["results"]) == 2  # default ALL

    with tenant_context(tenant_a.pk):
        TenantSetting.objects.create(key="orders.sales_visibility", value="ASSIGNED_RETAILERS")
    cache.clear()
    assert [r["id"] for r in sales.get(f"{API}/retailers/").json()["results"]] == [mine["id"]]
    assert sales.get(f"{API}/retailers/{other['id']}/").status_code == 404
    bulk = sales.post(
        f"{API}/retailers/bulk/",
        {"retailer_ids": [mine["id"], other["id"]], "action": "block", "value": "Check"},
        format="json",
    )
    assert bulk.json() == {"changed": 1}  # only the visible one
    assert len(owner.get(f"{API}/retailers/").json()["results"]) == 2  # owners see all
    people = owner.get(f"{API}/retailers/salespeople/").json()
    assert str(salesperson.pk) in {p["id"] for p in people}


def test_retailers_are_isolated(owner, tenant_a, tenant_b):
    retailer = _create(owner).json()
    other = _client(tenant_b)
    base = f"{API}/retailers/{retailer['id']}/"
    assert other.get(f"{API}/retailers/").json()["results"] == []
    assert other.get(base).status_code == 404
    assert other.patch(base, {"shop_name": "X"}, format="json").status_code == 404
    assert other.delete(base).status_code == 404
    for path in ("credit/", "block/", "unblock/", "resend-welcome/", "addresses/"):
        body = {
            "credit_limit": "1",
            "payment_terms_days": 1,
            "reason": "x",
            "kind": "BILLING",
            "line1": "a",
            "city": "b",
            "pincode": "411001",
            "state_code": "27",
        }
        method = other.patch if path == "credit/" else other.post
        assert method(f"{base}{path}", body, format="json").status_code == 404, path
    assert other.post(
        f"{API}/retailers/bulk/",
        {"retailer_ids": [retailer["id"]], "action": "block"},
        format="json",
    ).json() == {"changed": 0}
    # The same mobile number is a separate shop under another distributor (ADR-015).
    assert _create(other).status_code == 201
    with tenant_context(tenant_a.pk):
        assert Retailer.objects.get().credit_limit is None
