"""Shop return requests (ADR-057 item 3): the shop asks within the window for what is still
returnable; staff approve (the return credit note, stock and messages as for any return) or reject;
the shop may cancel while it waits; settings, the dashboard count and isolation."""

from datetime import timedelta
from decimal import Decimal as D
from typing import Any

import pytest
from django.core.cache import cache

from apps.accounts.tests.factories import make_staff_in
from apps.billing import returns
from apps.billing.models import CreditNote, ReturnRequest
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.models import StockLevel
from apps.inventory.tests.helpers import make_product
from apps.ledger.tests.helpers import check_ledger
from apps.notifications.models import Notification
from apps.orders.tests.helpers import add_stock, client_for, make_shop, settings, shop_client
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
SHOP, API = "/api/v1/shop", "/api/v1"


@pytest.fixture
def world(tenant_a, tenant_b, django_capture_on_commit_callbacks):
    cache.clear()
    settings(
        tenant_a, notifications__quiet_hours_start="00:00", notifications__quiet_hours_end="00:00"
    )
    owner = make_staff_in(tenant_a, "OWNER")
    tea = make_product(tenant_a, "TEA", base_price=D("100"))
    salt = make_product(tenant_a, "SALT", base_price=D("20"))
    add_stock(tenant_a, tea, "50")
    add_stock(tenant_a, salt, "50")
    shop = make_shop(tenant_a, "9876500121", shop_name="Laxmi Stores")
    run = lambda: django_capture_on_commit_callbacks(execute=True)  # noqa: E731
    with run():
        invoice = ship_invoice(tenant_a, shop, owner, (tea, "10"), (salt, "5"))
    with tenant_context(tenant_a.pk):
        tea_line, salt_line = invoice.lines.order_by("line_no")
    yield {
        "t": tenant_a,
        "owner": owner,
        "shop": shop,
        "tea": tea,
        "invoice": invoice,
        "tea_line": tea_line,
        "salt_line": salt_line,
        "staff": client_for(tenant_a, owner),
        "warehouse": client_for(tenant_a, make_staff_in(tenant_a, "WAREHOUSE")),
        "mine": shop_client(tenant_a, shop),
        "other_shop": shop_client(tenant_a, make_shop(tenant_a, "9876500122")),
        "b": client_for(tenant_b, make_staff_in(tenant_b, "OWNER")),
        "run": run,
    }
    cache.clear()


def ask(world: dict[str, Any], *lines: tuple[Any, str], client: Any = None) -> Any:
    body = {
        "invoice": str(world["invoice"].pk),
        "reason": "DAMAGED",
        "note": "Packets torn",
        "lines": [{"invoice_line": str(line.pk), "quantity": q} for line, q in lines],
    }
    with world["run"]():
        return (client or world["mine"]).post(f"{SHOP}/return-requests/", body, format="json")


def returnable(world: dict[str, Any]) -> dict[str, str]:
    detail = world["mine"].get(f"{SHOP}/invoices/{world['invoice'].pk}/").json()
    lines = {line["id"]: line["description"] for line in detail["lines"]}
    return {lines[row["invoice_line_id"]]: row["quantity"] for row in detail["returnable"]}


def messages(world: dict[str, Any], code: str) -> list[Notification]:
    with tenant_context(world["t"].pk):
        return list(Notification.objects.filter(event_code=code, channel="IN_APP"))


@covers(
    "shop-return-requests",
    "return-requests",
    "return-request",
    "return-request-approve",
)
def test_the_shop_asks_and_staff_approve_into_a_credit_note(world):
    assert returnable(world) == {"Product TEA": "10.000", "Product SALT": "5.000"}
    too_much = ask(world, (world["tea_line"], "11"))
    assert too_much.status_code == 400
    asked = ask(world, (world["tea_line"], "4"), (world["salt_line"], "5"))
    assert asked.status_code == 201, asked.json()
    request = asked.json()
    assert request["status"] == "REQUESTED" and request["number"].startswith("RR-")
    assert returnable(world) == {"Product TEA": "6.000", "Product SALT": "0.000"}
    [told] = messages(world, "return.requested")
    assert told.recipient_id == world["owner"].pk and "4 Product TEA" in told.body
    # Another shop and another distributor see none of it.
    assert ask(world, (world["tea_line"], "1"), client=world["other_shop"]).status_code == 404
    url = f"{API}/return-requests/{request['id']}/"
    assert world["b"].get(url).status_code == 404
    assert world["b"].get(f"{API}/return-requests/").json()["results"] == []
    assert world["warehouse"].get(f"{API}/return-requests/").status_code == 403

    listed = world["staff"].get(f"{API}/return-requests/", {"status": "REQUESTED"}).json()
    assert [r["number"] for r in listed["results"]] == [request["number"]]
    tea, salt = request["lines"]
    with world["run"]():
        approved = world["staff"].post(
            f"{url}approve/",
            {
                "lines": [
                    {"line": tea["id"], "quantity": "3", "disposition": "RETURN_TO_STOCK"},
                    {"line": salt["id"], "quantity": "0"},
                ]
            },
            format="json",
        )
    assert approved.status_code == 200, approved.json()
    body = approved.json()
    assert body["status"] == "APPROVED" and body["credit_note"]["number"]
    assert [(x["approved_quantity"], x["disposition"]) for x in body["lines"]] == [
        ("3.000", "RETURN_TO_STOCK"),
        ("0.000", ""),
    ]
    with tenant_context(world["t"].pk):
        note = CreditNote.objects.get(pk=body["credit_note"]["id"])
        tea_stock = StockLevel.objects.get(product=world["tea"]).quantity_on_hand
    assert (note.kind, note.return_reason, note.grand_total) == ("RETURN", "DAMAGED", D("315.00"))
    assert tea_stock == D("43")  # 50 - 10 sent + 3 back
    [shop_told] = messages(world, "return.approved")
    assert note.number in shop_told.body
    assert world["staff"].post(f"{url}approve/", {"lines": []}, format="json").status_code == 409
    assert returnable(world) == {"Product TEA": "7.000", "Product SALT": "5.000"}
    check_ledger(world["t"])


@covers("return-request-reject")
def test_staff_reject_with_a_reason_the_shop_sees(world):
    request = ask(world, (world["tea_line"], "2")).json()
    url = f"{API}/return-requests/{request['id']}/reject/"
    assert world["staff"].post(url, {"reason": " "}, format="json").status_code == 400
    assert world["b"].post(url, {"reason": "No"}, format="json").status_code == 404
    with world["run"]():
        rejected = world["staff"].post(url, {"reason": "Sold 40 days ago"}, format="json")
    assert rejected.json()["status"] == "REJECTED"
    [told] = messages(world, "return.rejected")
    assert "Sold 40 days ago" in told.body
    assert returnable(world)["Product TEA"] == "10.000"  # free to ask again


@covers("shop-return-request-cancel")
def test_the_shop_cancels_while_it_waits(world):
    request = ask(world, (world["tea_line"], "2")).json()
    url = f"{SHOP}/return-requests/{request['id']}/cancel/"
    assert world["other_shop"].post(url).status_code == 404
    assert world["mine"].post(url).json()["status"] == "CANCELLED"
    assert world["mine"].post(url).status_code == 409
    mine = world["mine"].get(f"{SHOP}/return-requests/").json()["results"]
    assert [r["status"] for r in mine] == ["CANCELLED"]


def test_the_window_and_the_setting(world, monkeypatch):
    detail = world["mine"].get(f"{SHOP}/invoices/{world['invoice'].pk}/").json()
    assert detail["can_request_return"] is True
    later = world["invoice"].invoice_date + timedelta(days=31)
    monkeypatch.setattr(returns, "today_ist", lambda: later)  # bills can't be back-dated
    late = ask(world, (world["tea_line"], "1"))
    assert late.status_code == 400 and "30 days" in str(late.json())
    settings(world["t"], returns__request_days=45)
    assert ask(world, (world["tea_line"], "1")).status_code == 201
    settings(world["t"], returns__shop_requests=False)
    refused = ask(world, (world["tea_line"], "1"))
    assert refused.status_code == 403
    detail = world["mine"].get(f"{SHOP}/invoices/{world['invoice'].pk}/").json()
    assert detail["can_request_return"] is False


def test_the_dashboard_counts_requests_to_decide(world):
    ask(world, (world["tea_line"], "1"))
    assert world["staff"].get(f"{API}/dashboard/").json()["action"]["return_requests"] == 1
    warehouse = world["warehouse"].get(f"{API}/dashboard/").json()["action"]
    assert warehouse["return_requests"] is None
    with tenant_context(world["t"].pk):
        assert ReturnRequest.objects.count() == 1
