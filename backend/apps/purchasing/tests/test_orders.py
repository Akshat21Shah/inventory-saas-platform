"""Purchase orders (ADR-053 item 5): numbering, the usual costs, packs and the GST estimate;
editing until something is received; sending (the supplier's copy by email, a link to share,
revisions); cancel and close; the copies with and without prices; roles, isolation, the flag."""

import re
from datetime import timedelta
from decimal import Decimal as D
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.core import mail
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.catalog.models import Unit
from apps.compliance.tests.conftest import switch_on
from apps.inventory.tests.helpers import make_product
from apps.notifications.models import Notification
from apps.orders.tests.helpers import client_for
from apps.purchasing import orders
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, SupplierProduct
from common.dates import today_ist
from common.errors import InvalidFields
from common.storage import InMemoryStorage
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"
YEAR = today_ist().year


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    InMemoryStorage.objects.clear()
    mail.outbox.clear()
    yield
    InMemoryStorage.objects.clear()


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    def _run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return _run


@pytest.fixture
def world(tenant_a, tenant_b, run):
    switch_on(tenant_a, "purchasing")
    switch_on(tenant_b, "purchasing")
    owner = make_staff_in(tenant_a, "OWNER")
    warehouse = make_staff_in(tenant_a, "WAREHOUSE")
    tea = make_product(tenant_a, "TEA", name="Tata Tea Gold", cost_price=D("80.00"))
    with tenant_context(tenant_a.pk):
        box = Unit.objects.get(code="BOX")
        biscuit = make_product(
            tenant_a, "BISCUIT", name="Parle-G", pack_unit=box, pack_size=D("12")
        )
    clients = {
        "owner": client_for(tenant_a, owner),
        "warehouse": client_for(tenant_a, warehouse),
        "sales": client_for(tenant_a, make_staff_in(tenant_a, "SALES")),
        "other": client_for(tenant_b, make_staff_in(tenant_b, "OWNER")),
    }
    supplier = run(
        clients["owner"].post,
        f"{API}/suppliers/",
        {"name": "Hindustan Traders", "email": "orders@hindustan.example.com", "lead_time_days": 5},
        format="json",
    ).json()
    return {
        "t": tenant_a,
        "b": tenant_b,
        "owner_user": owner,
        "warehouse_user": warehouse,
        **clients,
        "tea": tea,
        "biscuit": biscuit,
        "supplier": supplier,
    }


def _lines(world: dict[str, Any], **costs: str) -> list[dict[str, Any]]:
    return [
        {
            "product_id": str(world["tea"].pk),
            "entered_qty": "10",
            **({"entered_cost": costs["tea"]} if "tea" in costs else {}),
        },
        {
            "product_id": str(world["biscuit"].pk),
            "entered_unit": "PACK",
            "entered_qty": "2",
            **({"entered_cost": costs["biscuit"]} if "biscuit" in costs else {}),
        },
    ]


def _create(world: dict[str, Any], run: Any, client: str = "owner", **body: Any) -> dict[str, Any]:
    response = run(
        world[client].post,
        f"{API}/purchase-orders/",
        {"supplier_id": world["supplier"]["id"], "lines": _lines(world, biscuit="60"), **body},
        format="json",
    )
    assert response.status_code == 201, response.json()
    created: dict[str, Any] = response.json()
    return created


def _send(world: dict[str, Any], run: Any, order_id: str, key: str | None = None) -> Any:
    return run(
        world["owner"].post,
        f"{API}/purchase-orders/{order_id}/send/",
        HTTP_IDEMPOTENCY_KEY=key or f"k-{uuid4().hex}",
    )


@covers("purchase-orders", "purchase-order")
def test_a_draft_takes_the_usual_costs_packs_and_estimates_gst(world, run):
    with tenant_context(world["t"].pk):
        SupplierProduct.objects.create(
            supplier_id=world["supplier"]["id"],
            product=world["tea"],
            supplier_code="HT-77",
            last_unit_cost=D("75.5000"),
        )
    order = _create(world, run)
    assert (order["number"], order["status"], order["revision"]) == (f"PO-{YEAR}-00001", "DRAFT", 0)
    assert order["expected_date"] == str(today_ist() + timedelta(days=5))  # the supplier's days
    tea, biscuit = order["lines"]
    # Tea: the supplier's last cost; 10 at 75.50.
    assert (tea["unit_cost"], tea["supplier_code"], tea["line_total"]) == (
        "75.5000",
        "HT-77",
        "755.00",
    )
    # Biscuits: 2 boxes of 12 at ₹60 a box = ₹5 a piece.
    assert (biscuit["quantity"], biscuit["unit_cost"], biscuit["entered_cost"]) == (
        "24.000",
        "5.0000",
        "60.0000",
    )
    assert (biscuit["line_total"], biscuit["due"]) == ("120.00", "24.000")
    assert (order["subtotal"], order["estimated_tax"]) == ("875.00", "43.75")  # 5% GST
    assert order["actions"] == ["edit", "send", "delete", "cancel"]
    assert order["pdf_status"] == "PENDING"  # printed once the order is saved
    assert (
        world["owner"].get(f"{API}/purchase-orders/{order['id']}/").json()["pdf_status"] == "READY"
    )
    second = _create(world, run, expected_date=str(today_ist() + timedelta(days=2)))
    assert second["number"] == f"PO-{YEAR}-00002"
    listed = world["owner"].get(f"{API}/purchase-orders/").json()["results"]
    assert [o["number"] for o in listed] == [f"PO-{YEAR}-00002", f"PO-{YEAR}-00001"]
    with tenant_context(world["t"].pk):
        assert AuditLog.objects.filter(action="purchasing.po_created").count() == 2


def test_order_details_are_checked(world, run):
    owner = world["owner"]
    base = {"supplier_id": world["supplier"]["id"]}
    bad = owner.post(
        f"{API}/purchase-orders/",
        {
            **base,
            "expected_date": str(today_ist() - timedelta(days=1)),
            "lines": [
                {"product_id": str(world["tea"].pk), "entered_unit": "PACK", "entered_qty": "1"},
                {"product_id": str(uuid4()), "entered_qty": "1"},
            ],
        },
        format="json",
    )
    assert set(bad.json()["error"]["details"]["fields"]) == {"lines.1", "lines.2"}
    twice = owner.post(
        f"{API}/purchase-orders/",
        {**base, "lines": [_lines(world)[0], _lines(world)[0]]},
        format="json",
    )
    assert "lines.2" in twice.json()["error"]["details"]["fields"]
    past = owner.post(
        f"{API}/purchase-orders/",
        {**base, "expected_date": str(today_ist() - timedelta(days=1)), "lines": _lines(world)},
        format="json",
    )
    assert "expected_date" in past.json()["error"]["details"]["fields"]
    theirs = (
        world["other"].post(f"{API}/suppliers/", {"name": "Bravo Supply"}, format="json").json()
    )
    refused = owner.post(
        f"{API}/purchase-orders/",
        {"supplier_id": theirs["id"], "lines": _lines(world)},
        format="json",
    )
    assert "supplier_id" in refused.json()["error"]["details"]["fields"]


def test_staff_who_cant_see_costs_neither_see_nor_change_them(world, run):
    order = _create(world, run)
    view = world["warehouse"].get(f"{API}/purchase-orders/{order['id']}/").json()
    assert (view["subtotal"], view["estimated_tax"]) == (None, None)
    assert {
        (line["unit_cost"], line["entered_cost"], line["line_total"]) for line in view["lines"]
    } == {(None, None, None)}
    listed = world["warehouse"].get(f"{API}/purchase-orders/").json()["results"]
    assert listed[0]["subtotal"] is None
    assert (
        world["warehouse"]
        .patch(
            f"{API}/purchase-orders/{order['id']}/",
            {"supplier_id": world["supplier"]["id"], "lines": _lines(world)},
            format="json",
        )
        .status_code
        == 403
    )
    # The service keeps an existing line's cost for such a person and refuses a typed one.
    tea_line = order["lines"][0]
    data = orders.OrderInput(
        supplier_id=world["supplier"]["id"],
        lines=[
            orders.OrderLineInput(world["tea"].pk, D("12"), id=UUID(tea_line["id"])),
            orders.OrderLineInput(
                world["biscuit"].pk, D("2"), "PACK", id=UUID(order["lines"][1]["id"])
            ),
        ],
    )
    with tenant_context(world["t"].pk):
        run(orders.update_order, order["id"], data, by=world["warehouse_user"])
        lines = list(PurchaseOrderLine.objects.filter(order_id=order["id"]).order_by("line_no"))
        assert [(line.quantity, line.unit_cost) for line in lines] == [
            (D("12.000"), D("80.0000")),
            (D("24.000"), D("5.0000")),
        ]
        with pytest.raises(InvalidFields) as refused:
            orders.update_order(
                order["id"],
                orders.OrderInput(
                    world["supplier"]["id"],
                    [orders.OrderLineInput(world["tea"].pk, D("1"), entered_cost=D("1"))],
                ),
                by=world["warehouse_user"],
            )
        assert refused.value.details["fields"]["lines"] == [
            "Only staff who can see costs can enter them."
        ]


@covers("purchase-order-send")
def test_sending_emails_the_suppliers_copy_and_gives_a_link_to_share(world, run):
    order = _create(world, run)
    # A draft has no copy of the supplier's details yet; it shows where sending will email it.
    assert (order["supplier_snapshot"], order["send_to_email"]) == (
        {},
        "orders@hindustan.example.com",
    )
    key = f"k-{uuid4().hex}"
    sent = _send(world, run, order["id"], key)
    assert sent.status_code == 200, sent.json()
    body = sent.json()
    assert (body["order"]["status"], body["order"]["revision"], body["emailed"]) == (
        "SENT",
        1,
        True,
    )
    assert body["order"]["actions"] == ["edit", "send", "receive", "cancel"]
    [email] = mail.outbox
    assert email.to == ["orders@hindustan.example.com"]
    assert email.subject == f"Purchase order PO-{YEAR}-00001 from Alpha"
    found = re.search(r"/public/documents/([A-Za-z0-9_-]+)/", str(email.body))
    assert found is not None, email.body
    token = found.group(1)
    opened = APIClient().get(
        f"/api/v1/public/documents/{token}/", HTTP_X_FORWARDED_HOST="alpha.localhost"
    )
    assert opened.status_code == 302
    with tenant_context(world["t"].pk):
        po = PurchaseOrder.objects.get(pk=order["id"])
        assert po.supplier_snapshot["email"] == "orders@hindustan.example.com"
        notification = Notification.objects.get(event_code="purchase_order.sent")
    assert opened["Location"].startswith(f"https://storage.test/{po.pdf_key}")
    assert (notification.recipient_id, str(notification.supplier_id)) == (
        None,
        world["supplier"]["id"],
    )
    assert "/public/documents/" in body["share_link"]
    # The same request again replays the answer: no second email.
    again = _send(world, run, order["id"], key)
    assert again.status_code == 200 and len(mail.outbox) == 1

    # Changed after sending: sent again as revision 2.
    changed = run(
        world["owner"].patch,
        f"{API}/purchase-orders/{order['id']}/",
        {"supplier_id": world["supplier"]["id"], "lines": _lines(world, tea="70", biscuit="60")},
        format="json",
    ).json()
    assert (changed["status"], changed["changed_since_sent"]) == ("SENT", True)
    resent = _send(world, run, order["id"]).json()
    assert (resent["order"]["revision"], resent["order"]["changed_since_sent"]) == (2, False)
    assert mail.outbox[-1].subject == f"Purchase order PO-{YEAR}-00001 (revised 2) from Alpha"
    with tenant_context(world["t"].pk):
        assert AuditLog.objects.filter(action="purchasing.po_sent").count() == 2


def test_a_supplier_without_email_gets_the_link_only(world, run):
    world["owner"].patch(
        f"{API}/suppliers/{world['supplier']['id']}/", {"email": ""}, format="json"
    )
    order = _create(world, run)
    assert order["send_to_email"] == ""
    body = _send(world, run, order["id"]).json()
    assert body["emailed"] is False and "/public/documents/" in body["share_link"]
    assert mail.outbox == []
    with tenant_context(world["t"].pk):
        row = Notification.objects.get(event_code="purchase_order.sent")
    assert (row.status, row.skip_reason) == ("SKIPPED", "NO_ADDRESS")


@covers("purchase-order-cancel", "purchase-order-close")
def test_cancel_before_anything_arrives_close_the_rest_after(world, run):
    owner = world["owner"]
    first = _create(world, run)
    _send(world, run, first["id"])
    url = f"{API}/purchase-orders/{first['id']}"
    assert run(owner.post, f"{url}/close/", {"reason": "x"}, format="json").status_code == 409
    assert (
        "reason"
        in run(owner.post, f"{url}/cancel/", {}, format="json").json()["error"]["details"]["fields"]
    )
    cancelled = run(
        owner.post, f"{url}/cancel/", {"reason": "Ordered elsewhere"}, format="json"
    ).json()
    assert (cancelled["status"], cancelled["closed_reason"], cancelled["actions"]) == (
        "CANCELLED",
        "Ordered elsewhere",
        [],
    )
    assert {line["due"] for line in cancelled["lines"]} == {"0.000"}
    for blocked in (
        owner.patch(
            f"{url}/",
            {"supplier_id": world["supplier"]["id"], "lines": _lines(world)},
            format="json",
        ),
        _send(world, run, first["id"]),
        owner.delete(f"{url}/"),
    ):
        assert blocked.status_code == 409

    second = _create(world, run)
    _send(world, run, second["id"])
    with tenant_context(world["t"].pk):  # 9a.6 receives; here: 4 of the 10 tea arrived
        PurchaseOrderLine.objects.filter(order_id=second["id"], line_no=1).update(
            qty_received=D("4")
        )
        PurchaseOrder.objects.filter(pk=second["id"]).update(status="PARTLY_RECEIVED")
    url = f"{API}/purchase-orders/{second['id']}"
    assert world["owner"].get(f"{url}/").json()["actions"] == ["receive", "close"]
    assert run(owner.post, f"{url}/cancel/", {"reason": "x"}, format="json").status_code == 409
    closed = run(
        owner.post, f"{url}/close/", {"reason": "Supplier out of stock"}, format="json"
    ).json()
    assert closed["status"] == "CLOSED"
    assert [
        (line["qty_received"], line["qty_cancelled"], line["due"]) for line in closed["lines"]
    ] == [
        ("4.000", "6.000", "0.000"),
        ("0.000", "24.000", "0.000"),
    ]
    with tenant_context(world["t"].pk):
        assert (
            AuditLog.objects.filter(
                action__in=["purchasing.po_cancelled", "purchasing.po_closed"]
            ).count()
            == 2
        )


def test_only_a_draft_is_deleted(world, run):
    order = _create(world, run)
    assert run(world["owner"].delete, f"{API}/purchase-orders/{order['id']}/").status_code == 204
    with tenant_context(world["t"].pk):
        assert not PurchaseOrder.objects.exists() and not PurchaseOrderLine.objects.exists()


@covers("purchase-order-pdf")
def test_the_copy_with_prices_needs_costs_view(world, run):
    order = _create(world, run)
    url = f"{API}/purchase-orders/{order['id']}/pdf/"
    priced = world["owner"].get(url).json()["url"]
    plain = world["warehouse"].get(url).json()["url"]
    assert "-no-prices" not in priced and "-no-prices" in plain
    files = InMemoryStorage.objects
    priced_html = next(v for k, v in files.items() if k.endswith(f"PO-{YEAR}-00001.pdf"))[
        0
    ].decode()
    plain_html = next(v for k, v in files.items() if k.endswith("-no-prices.pdf"))[0].decode()
    assert (
        "75.50" not in plain_html
        and "Rate" not in plain_html
        and "Copy without prices" in plain_html
    )
    assert "Rate (₹)" in priced_html and "Draft" in priced_html


def test_filters_late_orders_and_search(world, run):
    late = _create(world, run)
    _send(world, run, late["id"])
    _create(world, run)
    with tenant_context(world["t"].pk):
        PurchaseOrder.objects.filter(pk=late["id"]).update(
            expected_date=today_ist() - timedelta(days=1)
        )
    owner = world["owner"]

    def numbers(params: dict[str, Any]) -> list[str]:
        found = owner.get(f"{API}/purchase-orders/", params).json()["results"]
        return [o["number"] for o in found]

    assert numbers({"late": True}) == [late["number"]]
    assert numbers({"status": "DRAFT"}) == [f"PO-{YEAR}-00002"]
    assert len(numbers({"search": "hindustan"})) == 2
    assert numbers({"supplier": world["supplier"]["id"], "search": "00001"}) == [late["number"]]
    assert owner.get(f"{API}/purchase-orders/{late['id']}/").json()["is_late"] is True


def test_another_distributor_and_other_roles(world, run):
    order = _create(world, run)
    other = world["other"]
    url = f"{API}/purchase-orders/{order['id']}"
    assert other.get(f"{url}/").status_code == 404
    assert other.get(f"{url}/pdf/").status_code == 404
    assert (
        run(other.post, f"{url}/send/", HTTP_IDEMPOTENCY_KEY=f"k-{uuid4().hex}").status_code == 404
    )
    assert run(other.post, f"{url}/cancel/", {"reason": "x"}, format="json").status_code == 404
    assert run(other.post, f"{url}/close/", {"reason": "x"}, format="json").status_code == 404
    assert other.delete(f"{url}/").status_code == 404
    assert other.get(f"{API}/purchase-orders/").json()["results"] == []
    assert world["sales"].get(f"{url}/").status_code == 403
    assert world["warehouse"].get(f"{url}/").status_code == 200
    assert (
        run(
            world["warehouse"].post, f"{url}/send/", HTTP_IDEMPOTENCY_KEY=f"k-{uuid4().hex}"
        ).status_code
        == 403
    )


def test_a_supplier_with_open_orders_cant_be_deleted(world, run):
    order = _create(world, run)
    refused = world["owner"].delete(f"{API}/suppliers/{world['supplier']['id']}/")
    assert refused.status_code == 400
    run(world["owner"].post, f"{API}/purchase-orders/{order['id']}/cancel/", {}, format="json")
    assert world["owner"].delete(f"{API}/suppliers/{world['supplier']['id']}/").status_code == 204


def test_purchase_orders_in_global_search(world, run):
    order = _create(world, run)
    found = world["owner"].get(f"{API}/search/", {"q": f"po-{YEAR}-1"}).json()
    assert (found["jump"]["type"], found["jump"]["id"]) == ("purchase_order", order["id"])
    assert found["jump"]["amount"] is None  # never the order's value
    assert world["sales"].get(f"{API}/search/", {"q": f"PO-{YEAR}-00001"}).json()["jump"] is None


def test_the_supplier_recipient_is_for_purchase_orders_only(world):
    from apps.notifications.rules import RuleInput, save_rules

    with tenant_context(world["t"].pk):
        with pytest.raises(InvalidFields) as refused:
            save_rules("order.placed", [RuleInput("SUPPLIER", ("EMAIL",))])
        assert refused.value.details["fields"]["rules"] == [
            "This recipient is only for purchase orders."
        ]
        with pytest.raises(InvalidFields):
            save_rules("purchase_order.sent", [RuleInput("SUPPLIER", ("WHATSAPP",))])
        save_rules("purchase_order.sent", [RuleInput("SUPPLIER", ("EMAIL",))])


def test_purchasing_switched_off(world, run):
    order = _create(world, run)
    from apps.platform.models import FeatureFlag, TenantFeature
    from apps.platform.selectors import invalidate_tenant_features

    with tenant_context(world["t"].pk):
        TenantFeature.objects.filter(flag=FeatureFlag.objects.get(code="purchasing")).update(
            enabled=False
        )
    invalidate_tenant_features(world["t"].pk)
    for response in (
        world["owner"].get(f"{API}/purchase-orders/"),
        world["owner"].get(f"{API}/purchase-orders/{order['id']}/"),
    ):
        assert (response.status_code, response.json()["error"]["code"]) == (
            403,
            "MODULE_NOT_ENABLED",
        )
    assert world["owner"].get(f"{API}/search/", {"q": order["number"]}).json()["jump"] is None


def test_cancelling_a_sent_order_emails_the_supplier_unless_staff_told_them(world, run):
    owner = world["owner"]
    first = _create(world, run)
    _send(world, run, first["id"])
    mail.outbox.clear()
    reason = {"reason": "Ordered elsewhere"}
    run(owner.post, f"{API}/purchase-orders/{first['id']}/cancel/", reason, format="json")
    [email] = mail.outbox
    assert email.to == ["orders@hindustan.example.com"]
    assert email.subject == f"Purchase order PO-{YEAR}-00001 cancelled by Alpha"
    assert "Ordered elsewhere" in str(email.body) and "/public/documents/" in str(email.body)

    second = _create(world, run)
    _send(world, run, second["id"])
    mail.outbox.clear()
    told = {"reason": "Told them on the phone", "notify_supplier": False}
    run(owner.post, f"{API}/purchase-orders/{second['id']}/cancel/", told, format="json")
    draft = _create(world, run)
    run(owner.post, f"{API}/purchase-orders/{draft['id']}/cancel/", {}, format="json")
    assert mail.outbox == []  # staff told them; a draft was never sent
    with tenant_context(world["t"].pk):
        emailed = [
            entry.metadata["supplier_emailed"]
            for entry in AuditLog.objects.filter(action="purchasing.po_cancelled").order_by(
                "created_at"
            )
        ]
    assert emailed == [True, False, False]
