"""The cheque bounce charge (ADR-057 item 4): off at ₹0; when set, a bounced cheque adds a debit
to the shop's account, due at once, without GST, named in the bounce message, on the bounced
receipt and on the payment."""

from decimal import Decimal as D

import pytest
from django.template.loader import render_to_string

from apps.accounts.tests.factories import make_staff_in
from apps.billing import documents
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.ledger.models import LedgerAdjustment, RetailerAccount
from apps.ledger.tests.helpers import check_ledger
from apps.notifications.models import Notification
from apps.orders.tests.helpers import add_stock, client_for, make_shop, settings
from apps.payments import services
from apps.payments.services import PaymentInput
from common.dates import today_ist
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(tenant_a, django_capture_on_commit_callbacks):
    settings(
        tenant_a, notifications__quiet_hours_start="00:00", notifications__quiet_hours_end="00:00"
    )
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a, "9876500131")
    product = make_product(tenant_a, "A", base_price=D("100"))
    add_stock(tenant_a, product, "10")
    run = lambda: django_capture_on_commit_callbacks(execute=True)  # noqa: E731
    with run():
        ship_invoice(tenant_a, shop, owner, (product, "2"))  # ₹210.00
    return {"t": tenant_a, "owner": owner, "shop": shop, "run": run}


def bounce(world):
    with world["run"](), tenant_context(world["t"].pk):
        cheque = services.record_payment(
            PaymentInput(
                retailer_id=world["shop"].pk,
                amount=D("210.00"),
                mode="CHEQUE",
                payment_date=today_ist(),
                cheque_number="004512",
            ),
            by=world["owner"],
        )
        return services.bounce_cheque(cheque.pk, reason="Insufficient funds", by=world["owner"])


def shop_message(world) -> str:
    with tenant_context(world["t"].pk):
        found = Notification.objects.get(
            event_code="payment.bounced", channel="IN_APP", recipient__user_type="RETAILER"
        )
        return str(found.body)


def test_no_charge_by_default(world):
    payment = bounce(world)
    assert payment.bounce_charge is None
    with tenant_context(world["t"].pk):
        assert not LedgerAdjustment.objects.exists()
    assert "bounce charge" not in shop_message(world)
    check_ledger(world["t"])


def test_a_set_charge_is_debited_and_named_everywhere(world):
    settings(world["t"], payments__cheque_bounce_charge="500")
    payment = bounce(world)
    with tenant_context(world["t"].pk):
        charge = LedgerAdjustment.objects.get()
        balance = RetailerAccount.objects.get(retailer=world["shop"]).balance
        html = render_to_string("billing/receipt.html", documents.receipt_context(payment))
    assert (charge.kind, charge.amount, charge.due_date) == ("DEBIT", D("500.00"), today_ist())
    assert charge.narration == f"Cheque bounce charge: cheque 004512 ({payment.number})"
    assert payment.bounce_charge_id == charge.pk
    assert balance == D("710.00")  # the bill due again, and the charge
    assert "A cheque bounce charge of ₹500.00 was added." in shop_message(world)
    assert "Cheque bounce charge of ₹500.00" in html
    detail = client_for(world["t"], world["owner"]).get(f"/api/v1/payments/{payment.pk}/")
    assert detail.json()["bounce_charge"] == "500.00"
    check_ledger(world["t"])
