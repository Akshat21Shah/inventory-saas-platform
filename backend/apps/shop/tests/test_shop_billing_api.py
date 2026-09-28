"""The shop's bills, statement, account and payments (PLAN §3.9): only its own; another shop's
documents and another tenant's are "not found"."""

from datetime import timedelta
from decimal import Decimal as D

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.billing import credit_notes
from apps.billing.credit_notes import ReturnLine
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.ledger import services as ledger
from apps.orders import transitions
from apps.orders.tests.helpers import add_stock, make_shop, place, settings, shop_client
from apps.payments import services as payments
from apps.payments.services import PaymentInput
from common.dates import today_ist
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
TODAY = today_ist()


@pytest.fixture
def world(tenant_a, django_capture_on_commit_callbacks):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    other = make_shop(tenant_a, "9876500071")
    a = make_product(tenant_a, "A", base_price=D("123.45"))
    add_stock(tenant_a, a, "100")
    with django_capture_on_commit_callbacks(execute=True):
        invoice = ship_invoice(tenant_a, shop, owner, (a, "2"))  # ₹259
        theirs = ship_invoice(tenant_a, other, owner, (a, "1"))
        with tenant_context(tenant_a.pk):
            note = credit_notes.issue_return(
                invoice.pk,
                [ReturnLine(invoice.lines.get().pk, D("1"))],
                reason="WRONG_ITEM",
                by=owner,
            )
            payment = payments.record_payment(
                PaymentInput(shop.pk, D("100.00"), "CASH", TODAY), by=owner
            )
    return {"t": tenant_a, "owner": owner, "shop": shop, "other": other, "a": a,
            "invoice": invoice, "theirs": theirs, "note": note, "payment": payment,
            "client": shop_client(tenant_a, shop)}  # fmt: skip


@covers("shop-invoices", "shop-invoice", "shop-invoice-pdf", "shop-credit-note-pdf")
def test_my_bills(world):
    c, invoice = world["client"], world["invoice"]
    rows = c.get("/api/v1/shop/invoices/").json()["results"]
    assert [r["number"] for r in rows] == [invoice.number]
    assert c.get("/api/v1/shop/invoices/?state=paid").json()["results"] == []
    assert len(c.get("/api/v1/shop/invoices/?state=unpaid").json()["results"]) == 1
    assert c.get("/api/v1/shop/invoices/?state=late").status_code == 400
    detail = c.get(f"/api/v1/shop/invoices/{invoice.pk}/").json()
    assert detail["balance_due"] == "29.00"  # ₹259 - ₹130 credit note - ₹100 paid
    assert [n["number"] for n in detail["credit_notes"]] == [world["note"].number]
    link = c.get(f"/api/v1/shop/invoices/{invoice.pk}/pdf/").json()
    assert link["status"] == "READY" and "-copies" not in link["url"]
    assert c.get(f"/api/v1/shop/credit-notes/{world['note'].pk}/pdf/").json()["url"]
    for url in (
        f"/api/v1/shop/invoices/{world['theirs'].pk}/",
        f"/api/v1/shop/invoices/{world['theirs'].pk}/pdf/",
    ):
        assert c.get(url).status_code == 404, url


@covers("shop-ledger", "shop-account")
def test_my_statement_and_account(world):
    c = world["client"]
    statement = c.get("/api/v1/shop/ledger/").json()
    assert [line["entry_type"] for line in statement["lines"]] == [
        "INVOICE",
        "CREDIT_NOTE",
        "PAYMENT",
    ]
    assert statement["closing_balance"] == "29.00"
    account = c.get("/api/v1/shop/account/").json()
    assert (account["position"]["balance"], account["overdue_bills"]) == ("29.00", 0)
    assert account["orders_blocked_for_overdue"] is False
    settings(world["t"], credit__block_overdue_after_days=5)
    with tenant_context(world["t"].pk):
        ledger.post_adjustment(
            world["shop"].pk,
            "OPENING_DEBIT",
            D("50.00"),
            on=TODAY - timedelta(days=10),
            narration="Old books",
            by=None,
        )
    account = c.get("/api/v1/shop/account/").json()
    assert account["orders_blocked_for_overdue"] is True
    assert account["position"]["overdue"] == "50.00"
    home = c.get("/api/v1/shop/home/").json()
    assert home["outstanding"] == {"balance": "79.00", "overdue": "50.00"}


@covers("shop-payments", "shop-payment", "shop-payment-receipt")
def test_my_payments(world):
    c, payment = world["client"], world["payment"]
    [row] = c.get("/api/v1/shop/payments/").json()["results"]
    assert (row["number"], row["amount"]) == (payment.number, "100.00")
    detail = c.get(f"/api/v1/shop/payments/{payment.pk}/").json()
    assert detail["used_for"][0]["target_number"] == world["invoice"].number
    assert c.get(f"/api/v1/shop/payments/{payment.pk}/receipt/").json()["status"] == "READY"
    other = shop_client(world["t"], world["other"])
    assert other.get(f"/api/v1/shop/payments/{payment.pk}/").status_code == 404
    assert other.get(f"/api/v1/shop/payments/{payment.pk}/receipt/").status_code == 404
    assert other.get("/api/v1/shop/payments/").json()["results"] == []


@covers("shop-order-confirmation")
def test_my_order_confirmation(world, django_capture_on_commit_callbacks):
    order = place(world["t"], world["shop"], (world["a"], "1"))
    with tenant_context(world["t"].pk), django_capture_on_commit_callbacks(execute=True):
        transitions.accept_order(order.pk, by=world["owner"])
    url = f"/api/v1/shop/orders/{order.pk}/confirmation/"
    assert world["client"].get(url).json()["status"] == "READY"
    assert shop_client(world["t"], world["other"]).get(url).status_code == 404


def test_staff_and_another_tenant_cannot_use_the_shop_api(world, tenant_b):
    from apps.orders.tests.helpers import client_for

    owner = client_for(world["t"], world["owner"])
    assert owner.get("/api/v1/shop/invoices/").status_code == 403
    outsider = shop_client(tenant_b, make_shop(tenant_b, "9876500081"))
    for url in (
        f"/api/v1/shop/invoices/{world['invoice'].pk}/",
        f"/api/v1/shop/invoices/{world['invoice'].pk}/pdf/",
        f"/api/v1/shop/credit-notes/{world['note'].pk}/pdf/",
        f"/api/v1/shop/payments/{world['payment'].pk}/",
        f"/api/v1/shop/payments/{world['payment'].pk}/receipt/",
    ):
        assert outsider.get(url).status_code == 404, url
    assert outsider.get("/api/v1/shop/invoices/").json()["results"] == []
    assert outsider.get("/api/v1/shop/ledger/").json()["lines"] == []
