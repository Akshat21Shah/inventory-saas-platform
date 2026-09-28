"""Invoice, credit-note and Order Confirmation APIs (PLAN §3.10): roles, sales visibility, PDF
links, credit notes with an Idempotency-Key, and another tenant seeing and changing nothing."""

from decimal import Decimal as D
from typing import Any
from uuid import uuid4

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.billing.models import CreditNote, Invoice
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.orders import transitions
from apps.orders.tests.helpers import add_stock, client_for, make_shop, place, settings
from apps.retailers.models import Retailer
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db


def key() -> dict[str, Any]:
    return {"HTTP_IDEMPOTENCY_KEY": f"k{uuid4().hex}"}


@pytest.fixture
def world(tenant_a, django_capture_on_commit_callbacks):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    a = make_product(tenant_a, "A", base_price=D("123.45"))
    add_stock(tenant_a, a, "100")
    with django_capture_on_commit_callbacks(execute=True):
        invoice = ship_invoice(tenant_a, shop, owner, (a, "10"))  # ₹1,296.00, PDF printed
    return {
        "t": tenant_a,
        "owner": owner,
        "shop": shop,
        "a": a,
        "invoice": invoice,
        "client": client_for(tenant_a, owner),
    }


def _line(world):
    with tenant_context(world["t"].pk):
        return world["invoice"].lines.get()


@covers("invoices", "invoice", "invoice-pdf", "invoice-regenerate-pdf")
def test_invoices_list_detail_and_pdf(world):
    c, invoice = world["client"], world["invoice"]
    rows = c.get("/api/v1/invoices/").json()["results"]
    assert [(r["number"], r["grand_total"], r["payment_status"]) for r in rows] == [
        (invoice.number, "1296.00", "UNPAID")
    ]
    assert c.get("/api/v1/invoices/?payment_status=PAID").json()["results"] == []
    assert c.get("/api/v1/invoices/?overdue=true").json()["results"] == []
    assert c.get(f"/api/v1/invoices/?search={world['shop'].code}").json()["results"]
    assert c.get("/api/v1/invoices/?payment_status=NOPE").status_code == 400
    detail = c.get(f"/api/v1/invoices/{invoice.pk}/").json()
    assert detail["totals"]["grand_total"] == "1296.00"
    assert detail["lines"][0]["credited_quantity"] == "0.000"
    assert (detail["seller"]["gstin"], detail["place_of_supply"]["code"]) == (
        world["t"].gstin,
        "27",
    )
    pdf = c.get(f"/api/v1/invoices/{invoice.pk}/pdf/")
    copies = c.get(f"/api/v1/invoices/{invoice.pk}/pdf/?copies=true").json()
    assert pdf.status_code == 200 and pdf.json()["url"].endswith("expires_in=300")
    assert "-copies.pdf" in copies["url"]
    again = c.post(f"/api/v1/invoices/{invoice.pk}/regenerate-pdf/")
    assert again.status_code == 202
    waiting = c.get(f"/api/v1/invoices/{invoice.pk}/pdf/")
    assert (waiting.status_code, waiting.json()) == (202, {"status": "PENDING", "url": None})


@covers("credit-notes", "credit-note", "credit-note-pdf", "credit-note-regenerate-pdf")
def test_credit_notes_are_created_once_per_key(world, django_capture_on_commit_callbacks):
    c, invoice, line = world["client"], world["invoice"], _line(world)
    body = {
        "invoice": str(invoice.pk),
        "kind": "RETURN",
        "reason": "DAMAGED",
        "lines": [{"invoice_line": str(line.pk), "quantity": "3", "disposition": "DAMAGED"}],
    }
    headers = key()
    with django_capture_on_commit_callbacks(execute=True):
        first = c.post("/api/v1/credit-notes/", body, format="json", **headers)
    assert first.status_code == 201, first.json()
    replay = c.post("/api/v1/credit-notes/", body, format="json", **headers)
    assert replay.json()["id"] == first.json()["id"]
    note = first.json()
    assert (note["grand_total"], note["lines"][0]["disposition"]) == ("389.00", "DAMAGED")
    assert note["used_for"][0]["target_number"] == invoice.number
    assert c.post("/api/v1/credit-notes/", body, format="json").status_code == 400  # no key
    missing_qty = {**body, "lines": [{"invoice_line": str(line.pk)}]}
    assert c.post("/api/v1/credit-notes/", missing_qty, format="json", **key()).status_code == 400
    adjust = {
        "invoice": str(invoice.pk),
        "kind": "PRICE_ADJUSTMENT",
        "note": "Agreed rate",
        "lines": [{"invoice_line": str(line.pk), "taxable_value": "100.00"}],
    }
    made = c.post("/api/v1/credit-notes/", adjust, format="json", **key())
    assert (made.status_code, made.json()["kind"]) == (201, "PRICE_ADJUSTMENT")
    listed = c.get(f"/api/v1/credit-notes/?invoice={invoice.pk}&kind=RETURN").json()["results"]
    assert [row["number"] for row in listed] == [note["number"]]
    assert c.get("/api/v1/credit-notes/?automatic=true").json()["results"] == []
    assert c.get(f"/api/v1/credit-notes/{note['id']}/").json()["reason_note"] == ""
    assert c.get(f"/api/v1/credit-notes/{note['id']}/pdf/").json()["status"] == "READY"
    assert c.post(f"/api/v1/credit-notes/{note['id']}/regenerate-pdf/").status_code == 202
    detail = c.get(f"/api/v1/invoices/{invoice.pk}/").json()
    assert detail["lines"][0]["credited_quantity"] == "3.000"
    assert [a["source_type"] for a in detail["applied"]] == ["CREDIT_NOTE", "CREDIT_NOTE"]


@covers("order-confirmation")
def test_the_order_confirmation(world, django_capture_on_commit_callbacks):
    order = place(world["t"], world["shop"], (world["a"], "1"))
    c = world["client"]
    assert c.get(f"/api/v1/orders/{order.pk}/confirmation/").status_code == 404  # not accepted
    with tenant_context(world["t"].pk), django_capture_on_commit_callbacks(execute=True):
        transitions.accept_order(order.pk, by=world["owner"])
    found = c.get(f"/api/v1/orders/{order.pk}/confirmation/").json()
    assert found["status"] == "READY" and found["url"]


def test_roles(world):
    invoice, line = world["invoice"], _line(world)
    warehouse = client_for(world["t"], make_staff_in(world["t"], "WAREHOUSE"))
    sales = client_for(world["t"], make_staff_in(world["t"], "SALES"))
    accounts = client_for(world["t"], make_staff_in(world["t"], "ACCOUNTS"))
    assert warehouse.get("/api/v1/invoices/").status_code == 403
    assert warehouse.get(f"/api/v1/invoices/{invoice.pk}/pdf/").status_code == 403
    assert sales.get(f"/api/v1/invoices/{invoice.pk}/").status_code == 200
    body = {
        "invoice": str(invoice.pk),
        "kind": "RETURN",
        "reason": "EXPIRED",
        "lines": [{"invoice_line": str(line.pk), "quantity": "1"}],
    }
    assert sales.post("/api/v1/credit-notes/", body, format="json", **key()).status_code == 403
    assert sales.post(f"/api/v1/invoices/{invoice.pk}/regenerate-pdf/").status_code == 403
    assert accounts.post("/api/v1/credit-notes/", body, format="json", **key()).status_code == 201


def test_sales_staff_see_only_their_shops(world):
    salesman = make_staff_in(world["t"], "SALES")
    settings(world["t"], orders__sales_visibility="ASSIGNED_RETAILERS")
    c, invoice = client_for(world["t"], salesman), world["invoice"]
    assert c.get("/api/v1/invoices/").json()["results"] == []
    assert c.get(f"/api/v1/invoices/{invoice.pk}/").status_code == 404
    assert c.get(f"/api/v1/invoices/{invoice.pk}/pdf/").status_code == 404
    with tenant_context(world["t"].pk):
        Retailer.objects.filter(pk=world["shop"].pk).update(salesperson=salesman)
    assert len(c.get("/api/v1/invoices/").json()["results"]) == 1


def test_another_tenant_sees_and_changes_nothing(world, tenant_b):
    invoice, line = world["invoice"], _line(world)
    with tenant_context(world["t"].pk):
        from apps.billing import credit_notes
        from apps.billing.credit_notes import ReturnLine

        note = credit_notes.issue_return(
            invoice.pk, [ReturnLine(line.pk, D("1"))], reason="DAMAGED", by=world["owner"]
        )
    order = place(world["t"], world["shop"], (world["a"], "1"))
    outsider = client_for(tenant_b, make_staff_in(tenant_b, "OWNER"))
    for url in (
        f"/api/v1/invoices/{invoice.pk}/",
        f"/api/v1/invoices/{invoice.pk}/pdf/",
        f"/api/v1/credit-notes/{note.pk}/",
        f"/api/v1/credit-notes/{note.pk}/pdf/",
        f"/api/v1/orders/{order.pk}/confirmation/",
    ):
        assert outsider.get(url).status_code == 404, url
    for url in ("/api/v1/invoices/", "/api/v1/credit-notes/"):
        assert outsider.get(url).json()["results"] == [], url
    for url, body, keyed in (
        (f"/api/v1/invoices/{invoice.pk}/regenerate-pdf/", {}, False),
        (f"/api/v1/credit-notes/{note.pk}/regenerate-pdf/", {}, False),
        (
            "/api/v1/credit-notes/",
            {
                "invoice": str(invoice.pk),
                "kind": "RETURN",
                "reason": "DAMAGED",
                "lines": [{"invoice_line": str(line.pk), "quantity": "1"}],
            },
            True,
        ),
    ):
        response = outsider.post(url, body, format="json", **(key() if keyed else {}))
        assert response.status_code == 404, (url, response.status_code)
    with tenant_context(world["t"].pk):
        assert CreditNote.objects.count() == 1
        assert Invoice.objects.get(pk=invoice.pk).pdf_status == "READY"
