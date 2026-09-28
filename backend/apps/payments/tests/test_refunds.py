"""Refunds (ADR-047 item 4): paid back from a shop's credit, oldest money first, never more than
the credit; own RFD series; audited; a voucher. If the money used bounces later, the refund is
owed again. API roles and another tenant seeing and changing nothing."""

from decimal import Decimal as D
from typing import Any
from uuid import uuid4

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.ledger.models import Allocation, LedgerEntry, RetailerAccount
from apps.ledger.tests.helpers import check_ledger
from apps.orders.tests.helpers import add_stock, client_for, make_shop
from apps.payments import services
from apps.payments.models import Refund
from apps.payments.services import PaymentInput, RefundInput
from common.dates import today_ist
from common.errors import DomainError, InvalidFields
from common.storage import get_storage
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
TODAY = today_ist()


def key() -> dict[str, Any]:
    return {"HTTP_IDEMPOTENCY_KEY": f"k{uuid4().hex}"}


@pytest.fixture
def world(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    return {"t": tenant_a, "owner": owner, "shop": shop, "client": client_for(tenant_a, owner)}


def _pay(world, amount, mode="CASH"):
    data = PaymentInput(
        world["shop"].pk, D(amount), mode, TODAY, cheque_number="000123" if mode == "CHEQUE" else ""
    )
    with tenant_context(world["t"].pk):
        return services.record_payment(data, by=world["owner"])


def _refund(world, amount, mode="CASH", **extra):
    with tenant_context(world["t"].pk):
        return services.record_refund(
            RefundInput(world["shop"].pk, D(amount), mode, extra.pop("on", TODAY), **extra),
            by=world["owner"],
        )


def _account(world):
    with tenant_context(world["t"].pk):
        return RetailerAccount.objects.get(retailer=world["shop"])


def test_a_refund_uses_the_oldest_credit(world, django_capture_on_commit_callbacks):
    first, second = _pay(world, "300.00"), _pay(world, "200.00")
    with django_capture_on_commit_callbacks(execute=True):
        refund = _refund(world, "350.00", "UPI", reference_no="UPI889")
    assert refund.number.startswith("RFD/") and refund.balance_due == 0
    account = _account(world)
    assert (account.balance, account.unapplied_credit) == (D("-150.00"), D("150.00"))
    with tenant_context(world["t"].pk):
        first.refresh_from_db()
        second.refresh_from_db()
        entry = LedgerEntry.objects.get(entry_type="REFUND")
        assert AuditLog.objects.filter(action="payments.refund_recorded").exists()
        refund.refresh_from_db()
    assert (first.unapplied_amount, second.unapplied_amount) == (D("0.00"), D("150.00"))
    assert (entry.debit, entry.reference_number) == (D("350.00"), refund.number)
    voucher = get_storage().get(refund.voucher_pdf_key).decode()
    for text in ("Refund voucher", refund.number, "₹350.00", first.number, second.number, "UPI889"):
        assert text in voucher, text
    check_ledger(world["t"])


def test_never_more_than_the_credit(world):
    _pay(world, "100.00")
    with pytest.raises(DomainError) as refused:
        _refund(world, "100.01")
    assert refused.value.code == "REFUND_EXCEEDS_CREDIT"
    assert refused.value.details == {"available": "100.00"}
    for bad in ({"amount": "0"}, {"amount": "1", "mode": "CHEQUE"}):
        with pytest.raises(InvalidFields):
            _refund(world, bad["amount"], bad.get("mode", "CASH"))
    with pytest.raises(InvalidFields):
        _refund(world, "1", on=TODAY.replace(year=TODAY.year + 1))
    with tenant_context(world["t"].pk):
        assert not Refund.objects.exists()


def test_a_refund_paid_from_a_bounced_cheque_is_owed_again(world):
    cheque = _pay(world, "400.00", "CHEQUE")  # credited on receipt
    refund = _refund(world, "400.00")
    with tenant_context(world["t"].pk):
        services.bounce_cheque(cheque.pk, reason="No funds", by=world["owner"])
        refund.refresh_from_db()
        allocation = Allocation.objects.get(refund=refund, amount__gt=0)
    assert refund.balance_due == D("400.00")  # the shop owes the money paid back
    assert _account(world).balance == D("400.00")
    dues = world["client"].get(f"/api/v1/retailers/{world['shop'].pk}/dues/").json()["dues"]
    assert [(d["kind"], d["balance_due"]) for d in dues] == [("REFUND", "400.00")]
    with tenant_context(world["t"].pk), pytest.raises(InvalidFields):
        services.reallocate(allocation.pk, to=[], reason="x", by=world["owner"])
    _pay(world, "400.00")  # covered by the next money
    with tenant_context(world["t"].pk):
        refund.refresh_from_db()
    assert refund.balance_due == 0
    check_ledger(world["t"])


def test_a_refund_after_a_return_credit(world):
    a = make_product(world["t"], "A", base_price=D("123.45"))
    add_stock(world["t"], a, "10")
    invoice = ship_invoice(world["t"], world["shop"], world["owner"], (a, "2"))  # ₹259
    _pay(world, "259.00")
    from apps.billing import credit_notes
    from apps.billing.credit_notes import ReturnLine

    with tenant_context(world["t"].pk):
        credit_notes.issue_return(
            invoice.pk,
            [ReturnLine(invoice.lines.get().pk, D("2"))],
            reason="WRONG_ITEM",
            by=world["owner"],
        )
    assert _account(world).unapplied_credit == D("259.00")
    _refund(world, "259.00", "BANK_TRANSFER")
    assert _account(world).balance == D("0.00")
    check_ledger(world["t"])


@covers("refunds", "refund", "refund-voucher", "refund-regenerate-voucher")
def test_refunds_api(world, tenant_b, django_capture_on_commit_callbacks):
    _pay(world, "500.00")
    c = world["client"]
    body = {
        "retailer": str(world["shop"].pk),
        "amount": "120.00",
        "mode": "CASH",
        "refund_date": str(TODAY),
    }
    headers = key()
    with django_capture_on_commit_callbacks(execute=True):
        made = c.post("/api/v1/refunds/", body, format="json", **headers)
    assert made.status_code == 201, made.json()
    assert (
        c.post("/api/v1/refunds/", body, format="json", **headers).json()["id"] == made.json()["id"]
    )
    refund = made.json()
    assert [(p["source_type"], p["amount"]) for p in refund["paid_from"]] == [("PAYMENT", "120.00")]
    assert c.get("/api/v1/refunds/").json()["results"][0]["number"] == refund["number"]
    assert c.get(f"/api/v1/refunds/{refund['id']}/voucher/").json()["status"] == "READY"
    assert c.post(f"/api/v1/refunds/{refund['id']}/regenerate-voucher/").status_code == 202
    too_much = {**body, "amount": "9999.00"}
    assert (
        c.post("/api/v1/refunds/", too_much, format="json", **key()).json()["error"]["code"]
        == "REFUND_EXCEEDS_CREDIT"
    )
    sales = client_for(world["t"], make_staff_in(world["t"], "SALES"))
    assert sales.get("/api/v1/refunds/").status_code == 200
    assert sales.post("/api/v1/refunds/", body, format="json", **key()).status_code == 403
    outsider = client_for(tenant_b, make_staff_in(tenant_b, "OWNER"))
    assert outsider.get("/api/v1/refunds/").json()["results"] == []
    for url in (f"/api/v1/refunds/{refund['id']}/", f"/api/v1/refunds/{refund['id']}/voucher/"):
        assert outsider.get(url).status_code == 404, url
    assert outsider.post(f"/api/v1/refunds/{refund['id']}/regenerate-voucher/").status_code == 404
    assert outsider.post("/api/v1/refunds/", body, format="json", **key()).status_code == 404
    with tenant_context(world["t"].pk):
        assert Refund.objects.count() == 1


class TestReversal:
    def test_restores_the_credit_exactly_and_marks_the_voucher(
        self, world, django_capture_on_commit_callbacks
    ):
        payment = _pay(world, "500.00")
        refund = _refund(world, "200.00")
        with tenant_context(world["t"].pk):
            with pytest.raises(InvalidFields):
                services.reverse_refund(refund.pk, reason=" ", by=world["owner"])
            with django_capture_on_commit_callbacks(execute=True):
                reversed_ = services.reverse_refund(
                    refund.pk, reason="Paid to the wrong shop", by=world["owner"]
                )
            payment.refresh_from_db()
            entry = LedgerEntry.objects.get(entry_type="REFUND_REVERSAL")
            assert AuditLog.objects.filter(action="payments.refund_reversed").exists()
            with pytest.raises(DomainError):  # only once
                services.reverse_refund(refund.pk, reason="Again", by=world["owner"])
            reversed_.refresh_from_db()
        account = _account(world)
        assert (account.balance, account.unapplied_credit) == (D("-500.00"), D("500.00"))
        assert payment.unapplied_amount == D("500.00")
        assert (entry.credit, entry.reverses.entry_type) == (D("200.00"), "REFUND")
        assert (reversed_.status, reversed_.reversal_reason) == (
            "REVERSED",
            "Paid to the wrong shop",
        )
        voucher = get_storage().get(reversed_.voucher_pdf_key).decode()
        assert "Reversed" in voucher and "Paid to the wrong shop" in voucher
        check_ledger(world["t"])

    def test_the_restored_credit_pays_what_is_owed_since(self, world):
        a = make_product(world["t"], "A", base_price=D("123.45"))
        add_stock(world["t"], a, "10")
        _pay(world, "300.00")
        refund = _refund(world, "300.00")
        invoice = ship_invoice(world["t"], world["shop"], world["owner"], (a, "2"))  # ₹259
        with tenant_context(world["t"].pk):
            services.reverse_refund(refund.pk, reason="Cheque not handed over", by=world["owner"])
            invoice.refresh_from_db()
        assert (invoice.balance_due, invoice.payment_status) == (D("0.00"), "PAID")
        assert _account(world).unapplied_credit == D("41.00")
        check_ledger(world["t"])

    def test_a_refund_owed_again_after_a_bounce_is_cancelled(self, world):
        cheque = _pay(world, "400.00", "CHEQUE")
        refund = _refund(world, "400.00")
        with tenant_context(world["t"].pk):
            services.bounce_cheque(cheque.pk, reason="No funds", by=world["owner"])
            assert _account(world).balance == D("400.00")  # the refund is owed
            services.reverse_refund(refund.pk, reason="Refund not paid out", by=world["owner"])
            refund.refresh_from_db()
        assert (refund.status, refund.balance_due) == ("REVERSED", D("0.00"))
        assert _account(world).balance == D("0.00")
        check_ledger(world["t"])


@covers("refund-reverse")
def test_reversing_a_refund_through_the_api(world, tenant_b):
    _pay(world, "500.00")
    refund = _refund(world, "120.00")
    url = f"/api/v1/refunds/{refund.pk}/reverse/"
    sales = client_for(world["t"], make_staff_in(world["t"], "SALES"))
    assert sales.post(url, {"reason": "x"}, format="json").status_code == 403
    outsider = client_for(tenant_b, make_staff_in(tenant_b, "OWNER"))
    assert outsider.post(url, {"reason": "x"}, format="json").status_code == 404
    c = world["client"]
    assert c.post(url, {"reason": ""}, format="json").status_code == 400
    done = c.post(url, {"reason": "Wrong amount"}, format="json")
    assert done.status_code == 200, done.json()
    assert (done.json()["status"], done.json()["reversal_reason"]) == ("REVERSED", "Wrong amount")
    assert c.post(url, {"reason": "Again"}, format="json").status_code == 409
    listed = c.get("/api/v1/refunds/").json()["results"][0]
    assert listed["status"] == "REVERSED"
