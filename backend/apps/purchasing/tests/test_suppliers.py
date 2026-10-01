"""Suppliers (ADR-053 item 4, flag ``purchasing``): the list and edits with their audit, who a
product is bought from (one preferred), the products bulk action, the Excel import, and the
one-time review that links past goods receipts to suppliers. Roles, isolation, flag off."""

from decimal import Decimal as D
from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.compliance.tests.conftest import switch_on
from apps.dataio.tests.helpers import commit, messages, upload, xlsx
from apps.inventory.models import StockInward
from apps.inventory.receipts import LineInput, ReceiptInput, create_and_post, create_draft
from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import client_for
from apps.purchasing.models import Supplier, SupplierProduct
from common.storage import InMemoryStorage
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"
GSTIN = "27AAGFK7315R1ZP"


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    InMemoryStorage.objects.clear()
    yield
    InMemoryStorage.objects.clear()


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    def _run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return _run


@pytest.fixture
def world(tenant_a, tenant_b):
    switch_on(tenant_a, "purchasing")
    switch_on(tenant_b, "purchasing")
    owner = make_staff_in(tenant_a, "OWNER")
    return {
        "t": tenant_a,
        "b": tenant_b,
        "owner_user": owner,
        "owner": client_for(tenant_a, owner),
        "manager": client_for(tenant_a, make_staff_in(tenant_a, "MANAGER")),
        "warehouse": client_for(tenant_a, make_staff_in(tenant_a, "WAREHOUSE")),
        "accounts": client_for(tenant_a, make_staff_in(tenant_a, "ACCOUNTS")),
        "sales": client_for(tenant_a, make_staff_in(tenant_a, "SALES")),
        "other": client_for(tenant_b, make_staff_in(tenant_b, "OWNER")),
        "tea": make_product(tenant_a, "TEA"),
        "soap": make_product(tenant_a, "SOAP"),
    }


def _create(client: APIClient, **fields: Any) -> dict[str, Any]:
    response = client.post(
        f"{API}/suppliers/", {"name": "Hindustan Traders", **fields}, format="json"
    )
    assert response.status_code == 201, response.json()
    body: dict[str, Any] = response.json()
    return body


@covers("suppliers", "supplier")
def test_suppliers_are_listed_edited_and_deleted_with_an_audit_trail(world):
    owner = world["owner"]
    first = _create(
        owner,
        name="  Hindustan   Traders ",
        gstin="27aagfk 7315r1zp",
        phone="+91 98220 12345",
        email="Orders@Hindustan.example.com",
        lead_time_days=5,
    )
    assert (first["code"], first["name"], first["gstin"]) == ("S-0001", "Hindustan Traders", GSTIN)
    assert (first["state_code"], first["state_name"]) == ("27", "Maharashtra")  # from the GSTIN
    assert first["email"] == "orders@hindustan.example.com"
    second = _create(owner, name="Patel Agencies", city="Nashik")
    assert second["code"] == "S-0002"

    listed = owner.get(f"{API}/suppliers/", {"search": "hindustn"}).json()["results"]
    assert [s["name"] for s in listed] == ["Hindustan Traders"]  # typos still find it
    assert [s["name"] for s in owner.get(f"{API}/suppliers/").json()["results"]] == [
        "Hindustan Traders",
        "Patel Agencies",
    ]

    url = f"{API}/suppliers/{second['id']}/"
    changed = owner.patch(url, {"payment_terms_days": 30, "is_active": False}, format="json")
    assert changed.status_code == 200, changed.json()
    assert (changed.json()["payment_terms_days"], changed.json()["is_active"]) == (30, False)
    assert [
        s["name"] for s in owner.get(f"{API}/suppliers/", {"active": True}).json()["results"]
    ] == ["Hindustan Traders"]
    assert owner.delete(url).status_code == 204
    assert owner.get(url).status_code == 404
    with tenant_context(world["t"].pk):
        actions = list(
            AuditLog.objects.filter(action__startswith="purchasing.supplier_")
            .order_by("created_at")
            .values_list("action", flat=True)
        )
    assert actions == [
        "purchasing.supplier_created",
        "purchasing.supplier_created",
        "purchasing.supplier_changed",
        "purchasing.supplier_deleted",
    ]


def test_supplier_details_are_checked(world):
    owner = world["owner"]
    _create(owner, gstin=GSTIN)
    refused = owner.post(
        f"{API}/suppliers/",
        {
            "name": "Copy Traders",
            "gstin": GSTIN,
            "phone": "12",
            "email": "nope",
            "pincode": "011001",
        },
        format="json",
    )
    assert refused.status_code == 400
    fields = refused.json()["error"]["details"]["fields"]
    assert set(fields) == {"gstin", "phone", "email", "pincode"}
    assert fields["gstin"] == ["Another supplier has this GSTIN."]
    wrong_state = owner.post(
        f"{API}/suppliers/",
        {"name": "X", "gstin": "29AAGFK7315R1ZL", "state_code": "27"},
        format="json",
    )
    assert "state_id" in wrong_state.json()["error"]["details"]["fields"]


def test_who_may_see_and_change_suppliers(world):
    supplier = _create(world["owner"])
    url = f"{API}/suppliers/{supplier['id']}/"
    for role in ("manager", "warehouse", "accounts"):
        assert world[role].get(url).status_code == 200, role
    assert world["sales"].get(url).status_code == 403  # no purchasing.view
    assert (
        world["manager"].patch(url, {"notes": "Calls on Mondays"}, format="json").status_code == 200
    )
    for role in ("warehouse", "accounts"):
        assert world[role].patch(url, {"notes": "x"}, format="json").status_code == 403, role
        assert (
            world[role].post(f"{API}/suppliers/", {"name": "X"}, format="json").status_code == 403
        )


def test_another_distributor_never_sees_them(world):
    supplier = _create(world["owner"], gstin=GSTIN)
    other = world["other"]
    assert other.get(f"{API}/suppliers/{supplier['id']}/").status_code == 404
    assert (
        other.patch(
            f"{API}/suppliers/{supplier['id']}/", {"name": "Mine"}, format="json"
        ).status_code
        == 404
    )
    assert other.delete(f"{API}/suppliers/{supplier['id']}/").status_code == 404
    assert other.get(f"{API}/suppliers/").json()["results"] == []
    # Each distributor may have its own supplier with the same GSTIN.
    assert (
        other.post(f"{API}/suppliers/", {"name": "Same", "gstin": GSTIN}, format="json").status_code
        == 201
    )


def test_purchasing_switched_off(world):
    from apps.platform.models import FeatureFlag, TenantFeature
    from apps.platform.selectors import invalidate_tenant_features

    with tenant_context(world["t"].pk):
        TenantFeature.objects.filter(flag=FeatureFlag.objects.get(code="purchasing")).update(
            enabled=False
        )
    invalidate_tenant_features(world["t"].pk)
    refused = world["owner"].get(f"{API}/suppliers/")
    assert (refused.status_code, refused.json()["error"]["code"]) == (403, "MODULE_NOT_ENABLED")
    refused = world["owner"].get(f"{API}/products/{world['tea'].pk}/suppliers/")
    assert refused.status_code == 403


# --- Products and their suppliers -------------------------------------------------------------


@covers("product-suppliers")
def test_a_product_has_several_suppliers_and_one_preferred(world):
    owner, tea = world["owner"], world["tea"]
    first, second = _create(owner), _create(owner, name="Patel Agencies")
    url = f"{API}/products/{tea.pk}/suppliers/"
    assert owner.get(url).json() == []
    links = [
        {"supplier_id": first["id"], "supplier_code": "HT-TEA", "pack_size": "12"},
        {"supplier_id": second["id"], "lead_time_days": 3},
    ]
    saved = owner.put(url, {"links": links}, format="json")
    assert saved.status_code == 200, saved.json()
    rows = saved.json()
    assert [(r["supplier_name"], r["is_preferred"]) for r in rows] == [
        ("Hindustan Traders", True),  # the first, when none is marked
        ("Patel Agencies", False),
    ]
    assert (rows[0]["supplier_code"], rows[0]["pack_size"]) == ("HT-TEA", "12.000")
    links[1]["is_preferred"] = True
    rows = owner.put(url, {"links": links}, format="json").json()
    assert [(r["supplier_name"], r["is_preferred"]) for r in rows] == [
        ("Patel Agencies", True),
        ("Hindustan Traders", False),
    ]
    two = owner.put(url, {"links": [{**links[0], "is_preferred": True}, links[1]]}, format="json")
    assert two.status_code == 400  # one preferred only
    assert owner.put(url, {"links": [links[0], links[0]]}, format="json").status_code == 400
    assert owner.put(url, {"links": []}, format="json").json() == []
    with tenant_context(world["t"].pk):
        assert AuditLog.objects.filter(action="purchasing.product_suppliers_changed").count() == 3

    theirs = (
        world["other"].post(f"{API}/suppliers/", {"name": "Bravo Supply"}, format="json").json()
    )
    refused = owner.put(url, {"links": [{"supplier_id": theirs["id"]}]}, format="json")
    assert refused.status_code == 400  # not this distributor's supplier
    assert world["other"].get(url).status_code == 404
    assert world["warehouse"].get(url).status_code == 200
    assert world["warehouse"].put(url, {"links": []}, format="json").status_code == 403


def test_the_last_cost_needs_costs_view(world):
    owner, tea = world["owner"], world["tea"]
    supplier = _create(owner)
    owner.put(
        f"{API}/products/{tea.pk}/suppliers/",
        {"links": [{"supplier_id": supplier["id"]}]},
        format="json",
    )
    with tenant_context(world["t"].pk):
        SupplierProduct.objects.filter(product=tea).update(last_unit_cost=D("41.5"))
    url = f"{API}/products/{tea.pk}/suppliers/"
    assert owner.get(url).json()[0]["last_unit_cost"] == "41.5000"
    assert world["accounts"].get(url).json()[0]["last_unit_cost"] == "41.5000"
    assert world["warehouse"].get(url).json()[0]["last_unit_cost"] is None


@covers("supplier-products")
def test_making_a_supplier_preferred_for_many_products(world):
    owner = world["owner"]
    first, second = _create(owner), _create(owner, name="Patel Agencies")
    tea, soap = world["tea"], world["soap"]
    owner.put(
        f"{API}/products/{tea.pk}/suppliers/",
        {"links": [{"supplier_id": first["id"]}]},
        format="json",
    )
    url = f"{API}/suppliers/{second['id']}/products/"
    response = owner.post(
        url, {"product_ids": [str(tea.pk), str(soap.pk), str(tea.pk)]}, format="json"
    )
    assert response.json() == {"changed": 2}
    assert owner.post(url, {"product_ids": [str(tea.pk)]}, format="json").json() == {"changed": 0}
    with tenant_context(world["t"].pk):
        preferred = dict(
            SupplierProduct.objects.filter(is_preferred=True).values_list(
                "product_id", "supplier__name"
            )
        )
        assert SupplierProduct.objects.filter(product=tea).count() == 2  # the first one stays
    assert preferred == {tea.pk: "Patel Agencies", soap.pk: "Patel Agencies"}
    listed = owner.get(url).json()["results"]
    assert [r["product_code"] for r in listed] == ["SOAP", "TEA"]
    b_product = make_product(world["b"], "B-1")
    assert owner.post(url, {"product_ids": [str(b_product.pk)]}, format="json").json() == {
        "changed": 0
    }
    assert world["other"].get(url).status_code == 404
    assert (
        world["warehouse"].post(url, {"product_ids": [str(tea.pk)]}, format="json").status_code
        == 403
    )


# --- Import --------------------------------------------------------------------------------------


@covers("suppliers-export")
def test_suppliers_import_and_export(world, run):
    owner = world["owner"]
    _create(owner, name="Patel Agencies")
    rows = [
        ["Supplier name", "GSTIN", "Contact person", "Phone", "Delivery days", "Payment days"],
        ["Hindustan Traders", GSTIN, "Ravi Shah", "9822012345", "5", "30"],
        ["patel  agencies", "", "Meena Patel", "", "", "15"],  # the existing one, by name
        ["Bad Supplier", "27ABCDE1234F1Z0", "", "12", "0", ""],
        ["Hindustan Traders", "", "", "", "", ""],  # twice
    ]
    job = upload(
        owner, run, xlsx(rows, name="suppliers.xlsx"), mode="ADD_OR_UPDATE", kind="SUPPLIERS"
    )
    assert job["status"] == "VALIDATED", job
    counts = job["counts"]
    assert (counts["new"], counts["update"], counts["error"]) == (1, 1, 2), job["errors"]
    problems = " ".join(messages(job))
    assert "GSTIN" in problems and "Delivery days" in problems and "once" in problems
    job = commit(owner, run, job)
    assert job["counts"]["applied"] == 2, job
    with tenant_context(world["t"].pk):
        hindustan = Supplier.objects.get(name="Hindustan Traders")
        patel = Supplier.objects.get(name="Patel Agencies")
    assert (hindustan.gstin, hindustan.lead_time_days, hindustan.payment_terms_days) == (
        GSTIN,
        5,
        30,
    )
    assert (patel.contact_name, patel.payment_terms_days) == ("Meena Patel", 15)
    refused = world["warehouse"].post(
        f"{API}/imports/",
        {"kind": "SUPPLIERS", "mode": "ADD_ONLY", "file": xlsx(rows, name="s.xlsx")},
        format="multipart",
    )
    assert refused.status_code == 403
    exported = owner.get(f"{API}/suppliers/export/", {"file_type": "csv"})
    assert exported.status_code == 200
    text = exported.content.decode("utf-8-sig")
    assert "Hindustan Traders" in text and "Patel Agencies" in text
    theirs = world["other"].get(f"{API}/suppliers/export/", {"file_type": "csv"})
    assert "Hindustan" not in theirs.content.decode("utf-8-sig")
    assert world["sales"].get(f"{API}/suppliers/export/").status_code == 403


# --- Suppliers from past goods receipts -------------------------------------------------------


@covers("suppliers-from-receipts")
def test_past_receipts_are_linked_to_suppliers_after_review(world):
    t, owner_user, tea = world["t"], world["owner_user"], world["tea"]
    with tenant_context(t.pk):
        for name in (
            "Hindustan Traders",
            "hindustan  traders",
            "Patel Agencies",
            "Patel Agencies",
            "",
        ):
            create_and_post(
                ReceiptInput([LineInput(tea.pk, D("1"), entered_cost=D("40"))], supplier_name=name),
                by=owner_user,
            )
        create_draft(
            ReceiptInput([LineInput(tea.pk, D("1"))], supplier_name="Gupta Bros"), by=owner_user
        )
    owner = world["owner"]
    patel = _create(owner, name="PATEL agencies")
    url = f"{API}/suppliers/from-receipts/"
    listed = owner.get(url).json()
    names = {row["name"]: row for row in listed}
    assert set(names) == {"Hindustan Traders", "Patel Agencies", "Gupta Bros"}
    assert names["Hindustan Traders"]["receipts"] == 2
    assert (names["Patel Agencies"]["match_id"], names["Patel Agencies"]["match_name"]) == (
        patel["id"],
        "PATEL agencies",
    )
    assert names["Hindustan Traders"]["match_id"] is None
    choices = [
        {"name": "Hindustan Traders", "new": True},
        {"name": "Patel Agencies", "supplier_id": patel["id"]},
    ]
    result = owner.post(url, {"choices": choices}, format="json")
    assert result.json() == {"suppliers_created": 1, "receipts_linked": 4}
    assert [row["name"] for row in owner.get(url).json()] == ["Gupta Bros"]  # not chosen yet
    with tenant_context(t.pk):
        linked = dict(
            StockInward.objects.filter(supplier__isnull=False).values_list(
                "supplier_name", "supplier__name"
            )
        )
        assert AuditLog.objects.filter(action="purchasing.receipt_suppliers_confirmed").count() == 1
    # The typed name stays on the receipt; the posted receipt is otherwise unchanged.
    assert linked == {
        "Hindustan Traders": "Hindustan Traders",
        "hindustan  traders": "Hindustan Traders",
        "Patel Agencies": "PATEL agencies",
    }
    assert owner.post(url, {"choices": [{"name": "Gupta Bros"}]}, format="json").status_code == 400
    assert world["warehouse"].get(url).status_code == 403
    assert world["other"].get(url).json() == []


def test_suppliers_in_global_search(world):
    owner = world["owner"]
    supplier = _create(owner, gstin=GSTIN)
    found = owner.get(f"{API}/search/", {"q": "hindustan"}).json()
    assert [(g["type"], [h["title"] for h in g["hits"]]) for g in found["groups"]] == [
        ("supplier", ["Hindustan Traders"])
    ]
    assert owner.get(f"{API}/search/", {"q": GSTIN}).json()["jump"]["id"] == supplier["id"]
    assert world["sales"].get(f"{API}/search/", {"q": "hindustan"}).json()["groups"] == []
    assert world["other"].get(f"{API}/search/", {"q": "hindustan"}).json()["groups"] == []


def test_a_receipt_names_its_supplier_and_a_posted_one_is_linked_only_once(world):
    from django.db import IntegrityError, transaction

    owner, tea = world["owner"], world["tea"]
    supplier = _create(owner)
    line = {"product_id": str(tea.pk), "entered_qty": "2", "entered_cost": "40"}
    made = owner.post(
        f"{API}/stock/inwards/",
        {"supplier_id": supplier["id"], "lines": [line], "post": True},
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"k-{uuid4().hex}",
    )
    assert made.status_code == 201, made.json()
    body = made.json()
    assert (body["supplier_id"], body["supplier_name"]) == (supplier["id"], "Hindustan Traders")
    theirs = (
        world["other"].post(f"{API}/suppliers/", {"name": "Bravo Supply"}, format="json").json()
    )
    refused = owner.post(
        f"{API}/stock/inwards/",
        {"supplier_id": theirs["id"], "lines": [line]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"k-{uuid4().hex}",
    )
    assert "supplier_id" in refused.json()["error"]["details"]["fields"]
    with tenant_context(world["t"].pk):
        other = Supplier.objects.create(code="S-9999", name="Other")
        with pytest.raises(IntegrityError), transaction.atomic():
            StockInward.objects.filter(pk=body["id"]).update(supplier=other)  # linked already
        with pytest.raises(IntegrityError), transaction.atomic():
            StockInward.objects.filter(pk=body["id"]).update(bill_number="X")  # still posted
