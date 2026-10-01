"""Global search (ADR-053, spec 5.17): typed numbers, GSTINs, mobiles and barcodes jump straight to
their record; text finds records grouped by kind; every kind needs its own view permission, sales
staff limited to their shops find only those shops' records, nothing crosses distributors and no
result carries cost data. The super admin finds distributors, and people only on the audited
path."""

import re
from decimal import Decimal as D
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in, make_super_admin
from apps.accounts.tokens import issue_tokens
from apps.audit.models import AuditLog
from apps.billing import credit_notes
from apps.billing.credit_notes import ReturnLine
from apps.billing.tests.helpers import ship_invoice
from apps.catalog.models import ProductBarcode
from apps.inventory.adjustments import AdjustmentInput, AdjustmentLineInput, create_adjustment
from apps.inventory.receipts import LineInput, ReceiptInput, create_and_post
from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import add_stock, client_for, make_shop, place, settings
from apps.payments import services as payments
from apps.payments.services import PaymentInput, RefundInput
from apps.retailers.models import Retailer
from apps.search.selectors import slug_of_address
from apps.search.sources import mobile_of
from common.dates import today_ist
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"
GSTIN = "27AAGFK7315R1ZP"
RECORDS = {
    "order": "order",
    "invoice": "invoice",
    "note": "credit_note",
    "payment": "payment",
    "refund": "refund",
    "receipt": "goods_receipt",
    "adjustment": "adjustment",
}


@pytest.fixture
def world(tenant_a, tenant_b):
    owner = make_staff_in(tenant_a, "OWNER", "asha.owner@alpha.example.com")
    sales = make_staff_in(tenant_a, "SALES")
    tea = make_product(tenant_a, "TEA", name="Tata Tea Gold", base_price=D("100"))
    soap = make_product(tenant_a, "SOAP", name="Lifebuoy Soap", base_price=D("10"))
    add_stock(tenant_a, tea, "50")
    add_stock(tenant_a, soap, "50")
    mine = make_shop(tenant_a, "9876500101", shop_name="Mine Stores", gstin=GSTIN)
    theirs = make_shop(tenant_a, "9876500102", shop_name="Their Stores")
    today = today_ist()
    with tenant_context(tenant_a.pk):
        ProductBarcode.objects.create(product=tea, barcode="8901234567890")
        Retailer.objects.filter(pk=mine.pk).update(salesperson=sales)
    invoice = ship_invoice(tenant_a, mine, owner, (tea, "1"))  # ₹105
    other_invoice = ship_invoice(tenant_a, theirs, owner, (soap, "1"))
    order = place(tenant_a, mine, (soap, "2"))
    with tenant_context(tenant_a.pk):
        payment = payments.record_payment(
            PaymentInput(mine.pk, D("200"), "UPI", today, reference_no="UTR778899"), by=owner
        )
        refund = payments.record_refund(RefundInput(mine.pk, D("50"), "CASH", today), by=owner)
        note = credit_notes.issue_return(
            invoice.pk, [ReturnLine(invoice.lines.get().pk, D("1"))], reason="DAMAGED", by=owner
        )
        receipt = create_and_post(
            ReceiptInput(
                [LineInput(tea.pk, D("5"), entered_cost=D("60"))],
                supplier_name="Hindustan Traders",
                bill_number="HT-991",
            ),
            by=owner,
        )
        adjustment = create_adjustment(
            AdjustmentInput(
                "DAMAGE", "Rats got the soap", [AdjustmentLineInput(soap.pk, "REMOVE", D("1"))]
            ),
            by=owner,
        ).adjustment
    b_owner = make_staff_in(tenant_b, "OWNER")
    b_shop = make_shop(tenant_b, "9876500201", shop_name="Bravo Mine Stores")
    b_tea = make_product(tenant_b, "TEA", name="Tata Tea Gold")
    add_stock(tenant_b, b_tea, "10")
    b_order = place(tenant_b, b_shop, (b_tea, "1"))
    return {
        "t": tenant_a,
        "b": tenant_b,
        "owner": client_for(tenant_a, owner),
        "sales": client_for(tenant_a, sales),
        "warehouse": client_for(tenant_a, make_staff_in(tenant_a, "WAREHOUSE")),
        "accounts": client_for(tenant_a, make_staff_in(tenant_a, "ACCOUNTS")),
        "other": client_for(tenant_b, b_owner),
        "tea": tea,
        "mine": mine,
        "theirs": theirs,
        "invoice": invoice,
        "other_invoice": other_invoice,
        "order": order,
        "payment": payment,
        "refund": refund,
        "note": note,
        "receipt": receipt,
        "adjustment": adjustment,
        "b_order": b_order,
    }


def find(client: APIClient, text: str) -> dict[str, Any]:
    response = client.get(f"{API}/search/", {"q": text})
    assert response.status_code == 200, response.json()
    body: dict[str, Any] = response.json()
    return body


def jump(client: APIClient, text: str) -> tuple[str, str] | None:
    hit = find(client, text)["jump"]
    return (hit["type"], hit["id"]) if hit else None


def kinds(body: dict[str, Any]) -> set[str]:
    return {group["type"] for group in body["groups"]}


def titles(body: dict[str, Any], kind: str) -> list[str]:
    return [h["title"] for g in body["groups"] if g["type"] == kind for h in g["hits"]]


def unpadded(number: str) -> str:
    """``INV/26-27/000012`` → ``inv/26-27/12``: typed in lower case without the padding."""
    return re.sub(r"0+(\d+)$", r"\1", number).lower()


def test_typed_text_is_read_as_people_type_it():
    assert mobile_of("98765 00101") == "+919876500101"
    assert mobile_of("+91-98765-00101") == "+919876500101"
    assert mobile_of("09876500101") == "+919876500101"
    assert mobile_of("1234567890") is None  # not a mobile number
    assert mobile_of("98765 00101 tea") is None
    assert slug_of_address("https://sharma.example.com/manage/orders") == "sharma"
    assert slug_of_address("sharma.localhost:3000") == "sharma"
    assert slug_of_address("Sharma Distributors") is None


@covers("search")
def test_document_numbers_jump_straight_to_their_record(world):
    owner = world["owner"]
    for key, kind in RECORDS.items():
        record = world[key]
        assert jump(owner, record.number) == (kind, str(record.pk)), record.number
        assert jump(owner, unpadded(record.number)) == (kind, str(record.pk)), record.number
    # A shipment's number leads to its order.
    assert jump(owner, f"{world['order'].number}/1") == ("order", str(world["order"].pk))
    body = find(owner, unpadded(world["invoice"].number))
    assert titles(body, "invoice")[0] == world["invoice"].number  # shown in its group too


def test_gstins_mobiles_and_barcodes_jump_too(world):
    owner, mine = world["owner"], str(world["mine"].pk)
    assert jump(owner, GSTIN.lower()) == ("shop", mine)
    assert jump(owner, "98765 00101") == ("shop", mine)
    assert jump(owner, "+91 98765-00101") == ("shop", mine)
    assert jump(owner, "8901234567890") == ("product", str(world["tea"].pk))
    assert jump(owner, "ORD-1999-000001") is None  # names nothing
    assert jump(owner, "Mine") is None  # text never jumps


def test_text_finds_records_grouped_by_kind(world):
    owner = world["owner"]
    body = find(owner, "  tata   tea ")
    assert body["query"] == "tata tea"
    assert titles(body, "product") == ["Tata Tea Gold"]
    assert titles(find(owner, "tata te"), "product") == ["Tata Tea Gold"]  # as you type
    assert titles(find(owner, "stores"), "shop") == ["Mine Stores", "Their Stores"]
    assert titles(find(owner, "UTR7788"), "payment") == [world["payment"].number]
    receipts = find(owner, "hindustan")
    assert titles(receipts, "goods_receipt") == [world["receipt"].number]
    assert titles(find(owner, "asha"), "staff") == ["asha.owner@alpha.example.com"]
    # Shop names don't search numbered documents.
    assert kinds(find(owner, "Mine")) == {"shop"}


def test_a_long_list_says_there_is_more(world):
    for n in range(6):
        make_shop(world["t"], f"98765002{n:02d}", shop_name=f"Corner Stores {n}")
    group = next(g for g in find(world["owner"], "corner")["groups"] if g["type"] == "shop")
    assert (len(group["hits"]), group["more"]) == (5, True)


def test_too_little_text_finds_nothing(world):
    assert find(world["owner"], " t ") == {"query": "t", "jump": None, "groups": []}
    long = find(world["owner"], "x" * 300)
    assert len(long["query"]) == 100


def test_results_never_carry_cost_data(world):
    def keys(value: Any) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {k for v in value.values() for k in keys(v)}
        if isinstance(value, list):
            return {k for v in value for k in keys(v)}
        return set()

    body = find(world["owner"], "GRN")
    receipt = next(h for g in body["groups"] for h in g["hits"] if g["type"] == "goods_receipt")
    assert receipt["amount"] is None  # never the receipt's cost
    assert receipt["detail"] == "Hindustan Traders"
    assert not {k for k in keys(body) if "cost" in k}


def test_each_kind_of_record_needs_its_own_view_permission(world):
    allowed = {
        "owner": set(RECORDS),
        "warehouse": {"order", "receipt", "adjustment"},
        "accounts": {"order", "invoice", "note", "payment", "refund", "receipt"},  # costs.view
        "sales": {"order", "invoice", "note", "payment", "refund"},
    }
    for role, keys in allowed.items():
        for key, kind in RECORDS.items():
            number = world[key].number
            assert (jump(world[role], number) is not None) == (key in keys), (role, key)
            if key not in keys:  # not in the grouped results either
                assert number not in titles(find(world[role], number), kind)
    assert titles(find(world["warehouse"], "stores"), "shop") == []  # no retailers.view
    assert titles(find(world["warehouse"], "tata"), "product") == ["Tata Tea Gold"]
    assert titles(find(world["accounts"], "asha"), "staff") == []  # staff.manage only


def test_sales_staff_limited_to_their_shops_find_only_those(world):
    settings(world["t"], orders__sales_visibility="ASSIGNED_RETAILERS")
    sales = world["sales"]
    assert titles(find(sales, "stores"), "shop") == ["Mine Stores"]
    assert jump(sales, world["invoice"].number) == ("invoice", str(world["invoice"].pk))
    assert jump(sales, world["other_invoice"].number) is None
    assert jump(sales, "98765 00102") is None  # their shop's mobile
    assert world["other_invoice"].number not in titles(find(sales, "INV"), "invoice")
    # Everyone else still finds both.
    assert titles(find(world["owner"], "stores"), "shop") == ["Mine Stores", "Their Stores"]


def test_another_distributor_finds_none_of_it(world):
    other = world["other"]
    for key in ("order", "invoice", "payment", "receipt", "adjustment"):
        assert jump(other, world[key].number) is None
    assert jump(other, GSTIN) is None and jump(other, "9876500101") is None
    assert titles(find(other, "stores"), "shop") == ["Bravo Mine Stores"]
    assert titles(find(other, "hindustan"), "goods_receipt") == []
    assert titles(find(world["owner"], "bravo"), "shop") == []
    # Each distributor numbers its own orders: the same number is each one's own record.
    assert jump(world["owner"], world["b_order"].number) != ("order", str(world["b_order"].pk))


def test_shops_and_the_platform_cannot_use_staff_search(world):
    from apps.orders.tests.helpers import shop_client

    assert (
        shop_client(world["t"], world["mine"]).get(f"{API}/search/", {"q": "tea"}).status_code
        == 403
    )
    admin = APIClient()
    admin.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(make_super_admin(), None).access}")
    assert admin.get(f"{API}/search/", {"q": "tea"}).status_code == 403
    assert APIClient().get(f"{API}/search/", {"q": "tea"}).status_code == 401


# --- The super admin ----------------------------------------------------------------------------


@pytest.fixture
def admin_client(db):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(make_super_admin(), None).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = "admin.localhost"
    return client


@covers("platform-search")
def test_the_super_admin_finds_distributors(world, admin_client):
    def search(text: str) -> dict[str, Any]:
        response = admin_client.get(f"{API}/platform/search/", {"q": text})
        assert response.status_code == 200, response.json()
        body: dict[str, Any] = response.json()
        return body

    alpha = str(world["t"].pk)
    assert titles(search("alph"), "tenant") == ["Alpha"]
    assert titles(search("private limited"), "tenant") == ["Alpha", "Bravo"]  # legal names
    assert search(world["t"].gstin.lower())["jump"]["id"] == alpha
    assert search("https://alpha.example.com/manage")["jump"]["id"] == alpha
    assert search("alpha.localhost:3000")["jump"]["id"] == alpha
    assert search("Alpha")["jump"] is None
    assert world["owner"].get(f"{API}/platform/search/", {"q": "alpha"}).status_code == 403


@covers("platform-search-users")
def test_people_across_distributors_only_on_the_audited_path(world, admin_client):
    response = admin_client.get(f"{API}/platform/search/users/", {"q": "asha.owner"})
    assert response.status_code == 200, response.json()
    [person] = response.json()
    assert (person["kind"], person["tenant_name"]) == ("STAFF", "Alpha")
    shops = admin_client.get(f"{API}/platform/search/users/", {"q": "98765 00101"}).json()
    assert [(p["kind"], p["shop_name"]) for p in shops] == [("SHOP", "Mine Stores")]
    entries = AuditLog.objects.filter(action="platform.users_searched").order_by("created_at")
    assert [e.metadata["query"] for e in entries] == ["asha.owner", "98765 00101"]
    assert [e.metadata["results"] for e in entries] == [1, 1]
    assert all(e.tenant_id is None for e in entries)
    refused = world["owner"].get(f"{API}/platform/search/users/", {"q": "asha"})
    assert refused.status_code == 403
    assert AuditLog.objects.filter(action="platform.users_searched").count() == 2
