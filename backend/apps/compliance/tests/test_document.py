"""The neutral e-invoice document (ADR-049 item 4) comes from the issued snapshots: parties,
supply, lines and totals of an inter-state B2B invoice, a credit note with its original invoice,
case-insensitive number keys; and which documents need an IRN."""

from decimal import Decimal as D

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.billing import credit_notes
from apps.billing.credit_notes import ReturnLine
from apps.billing.tests.helpers import ship_invoice
from apps.compliance import document, rules
from apps.compliance.tests.conftest import switch_on
from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import add_stock, make_shop
from apps.platform.tests.factories import make_gstin
from apps.retailers.services import AddressInput, create_retailer
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


@pytest.fixture
def sale(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER")
    laptop = make_product(tenant_a, "LAP-1", name="Laptop", hsn_code="8471", base_price=D("30000"))
    add_stock(tenant_a, laptop, "10")
    with tenant_context(tenant_a.pk):
        shop = create_retailer(
            shop_name="Kaveri Traders",
            phone="9876500071",
            gstin=make_gstin(7001, "29"),
            billing=AddressInput("4 MG Road", "Bengaluru", "560001", "29"),
            send_welcome=False,
        )
    local = make_shop(tenant_a, "9876500072", shop_name="Ganesh Kirana")
    invoice = ship_invoice(tenant_a, shop, owner, (laptop, "2"))
    return {
        "t": tenant_a,
        "owner": owner,
        "shop": shop,
        "local": local,
        "invoice": invoice,
        "laptop": laptop,
    }


def test_an_inter_state_b2b_invoice(sale):
    t, invoice = sale["t"], sale["invoice"]
    with tenant_context(t.pk):
        doc = document.invoice_document(invoice)
    assert doc["document"] == {
        "type": "INVOICE",
        "number": invoice.number,
        "number_key": invoice.number.upper(),
        "date": invoice.invoice_date.isoformat(),
        "financial_year": invoice.fy,
    }
    assert doc["supply"] == {
        "category": "B2B",
        "type": "INTER",
        "reverse_charge": False,
        "place_of_supply": "29",
    }
    assert doc["seller"]["gstin"] == t.gstin
    assert (doc["seller"]["pincode"], doc["seller"]["state_code"]) == (t.pincode, "27")
    assert doc["buyer"]["gstin"] == sale["shop"].gstin
    assert (doc["buyer"]["legal_name"], doc["buyer"]["pincode"], doc["buyer"]["state_code"]) == (
        "Kaveri Traders",
        "560001",
        "29",
    )
    assert doc["ship_to"] is None  # delivered to the billing address
    [line] = doc["lines"]
    assert line["hsn_code"] == "8471" and line["quantity"] == "2.000"
    assert (line["taxable_value"], line["igst_amount"], line["cgst_amount"]) == (
        "60000.00",
        "3000.00",
        "0.00",
    )
    assert doc["totals"]["grand_total"] == f"{invoice.grand_total:.2f}" == "63000.00"


def test_a_credit_note_names_its_invoice(sale):
    t, invoice = sale["t"], sale["invoice"]
    with tenant_context(t.pk):
        note = credit_notes.issue_return(
            invoice.pk,
            [ReturnLine(invoice.lines.get().pk, D("1"))],
            reason="DAMAGED",
            note="",
            by=sale["owner"],
        )
        doc = document.credit_note_document(note)
    assert doc["document"]["type"] == "CREDIT_NOTE"
    assert doc["original_invoice"] == {
        "number": invoice.number,
        "date": invoice.invoice_date.isoformat(),
    }
    [line] = doc["lines"]
    assert (line["quantity"], line["taxable_value"], line["igst_amount"]) == (
        "1.000",
        "30000.00",
        "1500.00",
    )
    assert doc["totals"]["grand_total"] == "31500.00"


def test_numbers_compare_in_upper_case():
    assert document.number_key(" inv/26-27/000001 ") == "INV/26-27/000001"


def test_only_b2b_documents_need_an_irn_and_only_with_the_module_on(sale):
    t = sale["t"]
    local_bill = ship_invoice(t, sale["local"], sale["owner"], (sale["laptop"], "1"))
    assert not rules.needs_irn(sale["invoice"])  # the module is off
    switch_on(t, "einvoice")
    assert rules.needs_irn(sale["invoice"])
    assert not rules.needs_irn(local_bill)  # B2C: never
