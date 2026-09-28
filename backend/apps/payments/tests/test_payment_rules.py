"""Payment rules approved at the Phase 5 backend checkpoint (2026-09-28, ADR-047): the payment's
own date drives the ledger; a payment dated in an earlier financial year is flagged; credit kept
although advances are off is shown to staff; handover follows the money."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.ledger.models import LedgerEntry
from apps.ledger.tests.helpers import check_ledger
from apps.orders.tests.helpers import add_stock, client_for, make_shop, settings
from apps.payments import selectors, services
from apps.payments.services import PaymentInput
from common.dates import today_ist
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
TODAY = today_ist()


@pytest.fixture
def world(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    a = make_product(tenant_a, "A", base_price=D("123.45"))
    add_stock(tenant_a, a, "100")
    invoice = ship_invoice(tenant_a, shop, owner, (a, "2"))  # ₹259
    return {"t": tenant_a, "owner": owner, "shop": shop, "invoice": invoice,
            "client": client_for(tenant_a, owner)}  # fmt: skip


def _pay(world, amount, mode="CASH", *, on=TODAY, by=None, collect=False):
    data = PaymentInput(
        world["shop"].pk, D(amount), mode, on, cheque_number="000123" if mode == "CHEQUE" else ""
    )
    with tenant_context(world["t"].pk):
        if collect:
            return services.collect_payment(data, by=by)
        return services.record_payment(data, by=by or world["owner"])


def test_a_cheque_cleared_later_is_accounted_on_its_payment_date(world):
    settings(world["t"], payments__cheque_credit_timing="ON_CLEARANCE")
    cheque = _pay(world, "259.00", "CHEQUE", on=TODAY - timedelta(days=6))
    with tenant_context(world["t"].pk):
        services.clear_cheque(cheque.pk, on=TODAY, by=world["owner"])
        entry = LedgerEntry.objects.get(entry_type="PAYMENT")
    assert entry.entry_date == TODAY - timedelta(days=6)
    statement = world["client"].get(f"/api/v1/retailers/{world['shop'].pk}/ledger/").json()
    [paid] = [line for line in statement["lines"] if line["entry_type"] == "PAYMENT"]
    assert paid["entry_date"] == str(TODAY - timedelta(days=6))
    assert statement["lines"][0] == paid  # listed on its date, before today's invoice
    check_ledger(world["t"])


def test_a_payment_dated_in_an_earlier_financial_year_is_flagged(world):
    start = date(TODAY.year if TODAY.month >= 4 else TODAY.year - 1, 4, 1)
    last_year = _pay(world, "10.00", on=start - timedelta(days=1))
    this_year = _pay(world, "10.00", on=start)
    c = world["client"]
    assert c.get(f"/api/v1/payments/{last_year.pk}/").json()["dated_in_previous_financial_year"]
    assert not c.get(f"/api/v1/payments/{this_year.pk}/").json()["dated_in_previous_financial_year"]
    assert this_year.number.split("/")[1] == last_year.number.split("/")[1]  # recording year
    dues = c.get(f"/api/v1/retailers/{world['shop'].pk}/dues/").json()
    assert dues["financial_year_start"] == str(start)


def test_credit_kept_although_advances_are_off_is_shown(world):
    settings(
        world["t"], payments__hold_advances=False, payments__cheque_credit_timing="ON_CLEARANCE"
    )
    cheque = _pay(world, "259.00", "CHEQUE")  # fits what is owed when recorded
    _pay(world, "259.00")  # then the shop pays in cash as well
    with tenant_context(world["t"].pk):
        services.clear_cheque(cheque.pk, by=world["owner"])
    c = world["client"]
    detail = c.get(f"/api/v1/payments/{cheque.pk}/").json()
    assert detail["held_as_credit_while_advances_off"] == "259.00"
    dues = c.get(f"/api/v1/retailers/{world['shop'].pk}/dues/").json()
    assert dues["credit_held_while_advances_off"] == "259.00"
    settings(world["t"], payments__hold_advances=True)
    assert (
        c.get(f"/api/v1/payments/{cheque.pk}/").json()["held_as_credit_while_advances_off"] is None
    )
    check_ledger(world["t"])


class TestHandover:
    @pytest.fixture
    def salesman(self, world):
        return make_staff_in(world["t"], "SALES")

    def test_a_collection_reversed_as_an_error_leaves_the_list(self, world, salesman):
        collected = _pay(world, "100.00", by=salesman, collect=True)
        with tenant_context(world["t"].pk):
            assert selectors.pending_handover_total() == D("100.00")
            services.reverse_payment(collected.pk, reason="Wrong shop", by=world["owner"])
            collected.refresh_from_db()
            assert collected.handover_status == "NOT_NEEDED"
            assert selectors.collections_pending_handover() == []
            entry = AuditLog.objects.get(action="payments.reversed")
            assert entry.metadata["left_pending_handover"] is True

    def test_bouncing_a_cheque_with_the_salesman_records_its_handover(self, world, salesman):
        cheque = _pay(world, "259.00", "CHEQUE", by=salesman, collect=True)
        with tenant_context(world["t"].pk):
            services.bounce_cheque(cheque.pk, reason="No funds", by=world["owner"])
            cheque.refresh_from_db()
            handed = AuditLog.objects.get(action="payments.handed_over")
            assert selectors.pending_handover_total() == 0
        assert (cheque.status, cheque.handover_status, cheque.handed_over_by_id) == (
            "BOUNCED",
            "HANDED_OVER",
            world["owner"].pk,
        )
        assert handed.metadata["automatic"] == "cheque bounced"
        assert handed.metadata["recorded_by"] == str(world["owner"].pk)
        check_ledger(world["t"])
