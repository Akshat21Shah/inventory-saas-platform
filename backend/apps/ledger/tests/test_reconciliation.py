"""Reconciliation (PLAN §4.5, §8): whatever happens, in any order and under any payment settings,
each shop's ledger balance = invoices - credited payments - credit notes ± adjustments, and
= what is still owed - unused credit (``check_ledger``, after every step)."""

from decimal import Decimal as D

import pytest
from django.core.cache import cache
from django.db import transaction
from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st

from apps.accounts.tests.factories import make_staff_in
from apps.billing import credit_notes
from apps.billing.credit_notes import ReturnLine
from apps.billing.models import Invoice
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.ledger import services as ledger
from apps.ledger.allocation import live_allocations
from apps.ledger.tests.helpers import check_ledger
from apps.orders.tests.helpers import add_stock, make_shop
from apps.payments import services as payments
from apps.payments.models import Payment
from apps.payments.services import PaymentInput
from apps.platform.services import set_tenant_settings
from common.dates import today_ist
from common.errors import DomainError
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db

money = st.decimals(min_value=D("1.00"), max_value=D("700.00"), places=2)
pick = st.integers(min_value=0, max_value=50)
step = st.one_of(
    st.tuples(st.just("ship"), st.sampled_from(["1", "2", "3"])),
    st.tuples(st.just("pay"), st.sampled_from(Payment.Mode.values), money),
    st.tuples(st.just("clear"), pick),
    st.tuples(st.just("bounce"), pick),
    st.tuples(st.just("reverse"), pick),
    st.tuples(st.just("return"), pick, st.sampled_from(["1", "2"])),
    st.tuples(st.just("adjust"), st.sampled_from(["DEBIT", "CREDIT"]), money),
    st.tuples(st.just("reallocate"), pick),
)


@pytest.fixture
def world(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER")
    product = make_product(tenant_a, "A", base_price=D("123.45"))
    add_stock(tenant_a, product, "10000")
    return {"t": tenant_a, "owner": owner, "a": product, "shops": iter(range(10**6))}


def _run(world, shop, action):
    t, owner = world["t"], world["owner"]
    kind = action[0]
    if kind == "ship":
        ship_invoice(t, shop, owner, (world["a"], action[1]))
        return
    with tenant_context(t.pk):
        mine = Payment.objects.filter(retailer=shop).order_by("created_at")
        if kind == "pay":
            _, mode, amount = action
            data = PaymentInput(
                shop.pk, amount, mode, today_ist(), cheque_number="1" if mode == "CHEQUE" else ""
            )
            payments.record_payment(data, by=owner)  # may refuse an advance when they're off
        elif kind in ("clear", "bounce", "reverse") and mine:
            payment = mine[action[1] % len(mine)]
            if kind == "clear":
                payments.clear_cheque(payment.pk, by=owner)
            elif kind == "bounce":
                payments.bounce_cheque(payment.pk, reason="Bounced", by=owner)
            else:
                payments.reverse_payment(payment.pk, reason="Error", by=owner)
        elif kind == "return":
            invoices = list(Invoice.objects.filter(retailer=shop).order_by("created_at"))
            if invoices:
                invoice = invoices[action[1] % len(invoices)]
                line = invoice.lines.get()
                credit_notes.issue_return(
                    invoice.pk,
                    [ReturnLine(line.pk, D(action[2]), "NOT_RETURNED")],
                    reason="DAMAGED",
                    by=owner,
                )
        elif kind == "adjust":
            ledger.post_adjustment(
                shop.pk, action[1], action[2], on=today_ist(), narration="Test", by=owner
            )
        elif kind == "reallocate":
            rows = live_allocations(retailer_id=shop.pk)
            if rows:
                row = rows[action[1] % len(rows)]
                payments.reallocate(row.pk, to=[], reason="Move", by=owner)


@settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(
    hold_advances=st.booleans(),
    cheque_timing=st.sampled_from(["ON_RECEIPT", "ON_CLEARANCE"]),
    steps=st.lists(step, min_size=1, max_size=10),
)
def test_the_ledger_always_reconciles(world, hold_advances, cheque_timing, steps):
    t = world["t"]
    with transaction.atomic():
        with tenant_context(t.pk):
            set_tenant_settings(
                {
                    "payments.hold_advances": hold_advances,
                    "payments.cheque_credit_timing": cheque_timing,
                },
                user=None,
            )
        cache.clear()
        shop = make_shop(t, f"98{next(world['shops']):08d}")
        for action in steps:
            try:
                with transaction.atomic():
                    _run(world, shop, action)
                event(f"{action[0]} done")
            except DomainError as refused:  # a refused step changes nothing
                event(f"{action[0]} refused: {refused.code}")
                assert refused.code in (
                    "PAYMENT_EXCEEDS_OUTSTANDING",
                    "INVALID_STATE_TRANSITION",
                    "VALIDATION_ERROR",
                ), refused.code
            check_ledger(t)
        transaction.set_rollback(True)
    cache.clear()
