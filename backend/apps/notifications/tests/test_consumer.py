"""Outbox events become notification rows (ADR-048): the right notification for the context, the
default and tenant rules, recipients, WhatsApp consent and the feature flag, missing addresses,
switched-off channels (never compulsory ones, never in-app), sandboxed templates, idempotency,
and another tenant receiving nothing."""

from decimal import Decimal as D
from typing import Any

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.notifications import consumer, tasks
from apps.notifications.models import (
    Notification,
    NotificationPreference,
    NotificationRule,
    NotificationTemplate,
)
from apps.orders import transitions
from apps.orders.tests.helpers import add_stock, make_shop, place, shop_user
from apps.payments import services as payments
from apps.payments.services import PaymentInput
from apps.platform import selectors
from apps.platform.models import FeatureFlag, TenantFeature
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.models import OutboxEvent
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
SKIP = Notification.SkipReason


@pytest.fixture
def world(tenant_a, django_capture_on_commit_callbacks):
    owner = make_staff_in(tenant_a, "OWNER")
    sales = make_staff_in(tenant_a, "SALES")
    warehouse = make_staff_in(tenant_a, "WAREHOUSE")
    shop = make_shop(tenant_a, email="shop@example.com")
    update_shop(shop, salesperson=sales)
    product = make_product(tenant_a, "P-1")
    add_stock(tenant_a, product, "100")
    return {
        "t": tenant_a,
        "owner": owner,
        "sales": sales,
        "warehouse": warehouse,
        "shop": shop,
        "login": shop_user(shop),
        "product": product,
        "run": lambda: django_capture_on_commit_callbacks(execute=True),
    }


def rows(world: dict[str, Any], code: str) -> list[Notification]:
    with tenant_context(world["t"].pk):
        return list(
            Notification.objects.filter(event_code=code)
            .select_related("recipient")
            .order_by("recipient__email", "channel")
        )


def who(found: list[Notification]) -> set[tuple[Any, str]]:
    return {(n.recipient_id, n.channel) for n in found}


def whatsapp(tenant: Any, enabled: bool = True) -> None:
    with tenant_context(tenant.pk):
        TenantFeature.objects.create(flag=FeatureFlag.objects.get(code="whatsapp"), enabled=enabled)
    selectors.invalidate_tenant_features(tenant.pk)


def update_shop(shop: Retailer, **fields: Any) -> None:
    with tenant_context(shop.tenant_id):
        Retailer.objects.filter(pk=shop.pk).update(**fields)
        shop.refresh_from_db()


def consent(shop: Retailer, agreed: bool = True) -> None:
    update_shop(shop, whatsapp_opt_in=agreed)


def test_a_shop_order_reaches_the_office_the_salesperson_and_the_shop(world):
    with world["run"]():
        order = place(world["t"], world["shop"], (world["product"], "2"))
    found = rows(world, "order.placed")
    assert who(found) == {
        (world["owner"].pk, "IN_APP"),  # orders.manage
        (world["sales"].pk, "IN_APP"),  # the shop's salesperson
        (world["login"].pk, "IN_APP"),
    }  # the warehouse role can't manage orders: nothing for it
    office = next(n for n in found if n.recipient_id == world["owner"].pk)
    assert office.status == "SENT" and office.sent_at is not None
    assert office.title == f"New order {order.number}"
    assert world["shop"].shop_name in office.body and "₹" in office.body
    assert office.data["path"] == f"/manage/orders/{order.pk}"
    assert office.data["url"].endswith(f"/manage/orders/{order.pk}")
    shop_row = next(n for n in found if n.recipient_id == world["login"].pk)
    assert shop_row.data["path"] == f"/shop/orders/{order.pk}"
    # Audiences (final review): the shop reads its own words, the office its own.
    assert shop_row.title == f"Order {order.number} placed"
    assert shop_row.body.startswith(f"Your order {order.number} for ₹")
    sales_row = next(n for n in found if n.recipient_id == world["sales"].pk)
    assert sales_row.body.startswith(f"{world['shop'].shop_name} placed order {order.number}")
    assert shop_row.retailer_id == world["shop"].pk


def test_an_event_delivered_twice_creates_nothing_new(world):
    with world["run"]():
        place(world["t"], world["shop"], (world["product"], "2"))
    event = OutboxEvent.objects.get(event_type="order.placed")
    before = len(rows(world, "order.placed"))
    tasks.dispatch_event(event_id=str(event.pk), tenant_id=str(world["t"].pk))
    assert len(rows(world, "order.placed")) == before


def test_whatsapp_needs_the_feature_and_the_shops_consent(world):
    def placed_for_shop() -> Notification:
        with world["run"]():
            place(
                world["t"], world["shop"], (world["product"], "1"), via="STAFF", by=world["owner"]
            )
        found = [n for n in rows(world, "order.placed_for_shop") if n.channel == "WHATSAPP"]
        return max(found, key=lambda n: n.created_at)

    first = placed_for_shop()
    assert (first.status, first.skip_reason) == ("SKIPPED", SKIP.FEATURE_OFF)
    whatsapp(world["t"])
    second = placed_for_shop()
    assert (second.status, second.skip_reason) == ("SKIPPED", SKIP.NO_WHATSAPP_OPT_IN)
    consent(world["shop"])
    third = placed_for_shop()
    assert (third.status, third.skip_reason, third.address) == ("SENT", "", world["shop"].mobile)
    assert third.body.startswith(f"{world['t'].name}:")  # names the distributor first
    assert third.data["whatsapp"]["template"] == "b2b_order_placed_for_shop"
    assert third.data["whatsapp"]["category"] == "UTILITY"
    assert third.data["whatsapp"]["parameters"][0] == world["t"].name


def test_an_invoice_goes_by_email_and_its_compulsory_channels_ignore_preferences(world):
    whatsapp(world["t"])
    consent(world["shop"])
    with tenant_context(world["t"].pk):
        for channel in ("EMAIL", "WHATSAPP", "IN_APP"):
            NotificationPreference.objects.create(
                user=world["login"], event_code="invoice.issued", channel=channel, enabled=False
            )
    with world["run"]():
        invoice = ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "2"))
    found = {n.channel: n for n in rows(world, "invoice.issued")}
    assert set(found) == {"IN_APP", "EMAIL", "WHATSAPP"}
    assert (found["EMAIL"].status, found["EMAIL"].address) == ("SENT", "shop@example.com")
    assert found["WHATSAPP"].status == "SENT"
    assert found["IN_APP"].status == "SENT"
    assert found["EMAIL"].data["document"] == {"kind": "INVOICE", "id": str(invoice.pk)}
    assert found["EMAIL"].data["compulsory"] is True
    assert invoice.number in found["IN_APP"].title


def test_a_shop_can_switch_off_other_events_but_never_in_app(world):
    update_shop(world["shop"], email="")
    with tenant_context(world["t"].pk):
        for channel in ("EMAIL", "IN_APP"):
            NotificationPreference.objects.create(
                user=world["login"], event_code="payment.received", channel=channel, enabled=False
            )
    with world["run"](), tenant_context(world["t"].pk):
        payments.record_payment(
            PaymentInput(world["shop"].pk, D("100.00"), "CASH", today_ist()), by=world["owner"]
        )
    found = {n.channel: n for n in rows(world, "payment.received")}
    assert found["IN_APP"].status == "SENT"
    assert (found["EMAIL"].status, found["EMAIL"].skip_reason) == ("SKIPPED", SKIP.NO_ADDRESS)
    assert found["WHATSAPP"].skip_reason == SKIP.FEATURE_OFF
    update_shop(world["shop"], email="shop@example.com")
    with world["run"](), tenant_context(world["t"].pk):
        payments.record_payment(
            PaymentInput(world["shop"].pk, D("50.00"), "CASH", today_ist()), by=world["owner"]
        )
    emails = [n for n in rows(world, "payment.received") if n.channel == "EMAIL"]
    assert {n.skip_reason for n in emails} == {SKIP.NO_ADDRESS, SKIP.TURNED_OFF}


def test_context_picks_the_notification(world):
    with world["run"]():
        order = place(world["t"], world["shop"], (world["product"], "1"))
    with world["run"](), tenant_context(world["t"].pk):
        transitions.cancel_order(
            order.pk, by=world["login"], reason="Ordered twice", retailer_id=world["shop"].pk
        )
    assert not rows(world, "order.cancelled")
    assert who(rows(world, "order.cancelled_by_shop")) == {
        (world["owner"].pk, "IN_APP"),
        (world["sales"].pk, "IN_APP"),  # the Sales role manages orders too
    }
    with world["run"](), tenant_context(world["t"].pk):
        cheque = payments.record_payment(
            PaymentInput(
                world["shop"].pk, D("80.00"), "CHEQUE", today_ist(), cheque_number="000777"
            ),
            by=world["owner"],
        )
        payments.bounce_cheque(cheque.pk, reason="Insufficient funds", by=world["owner"])
    assert not rows(world, "payment.reversed")
    bounced = rows(world, "payment.bounced")
    assert {n.recipient_id for n in bounced} == {
        world["login"].pk,
        world["owner"].pk,  # payments.record
        world["sales"].pk,
    }
    shop_in_app = next(
        n for n in bounced if n.recipient_id == world["login"].pk and n.channel == "IN_APP"
    )
    assert "000777" in shop_in_app.title and "Insufficient funds" in shop_in_app.body
    whatsapp = next(n for n in bounced if n.channel == "WHATSAPP")  # decision 4 of the checkpoint
    dated = today_ist().strftime("%d-%m-%Y")
    for text in ("000777", f"dated {dated}", "₹80.00", "Your balance: nothing to pay."):
        assert text in whatsapp.body, text
    assert whatsapp.data["whatsapp"]["parameters"][-1] == "nothing to pay"


def test_notification_codes_split_by_context():
    def event(kind: str, **payload: Any) -> OutboxEvent:
        return OutboxEvent(event_type=kind, payload=payload)

    assert (
        consumer.notification_code(event("payment.reversed", status="REVERSED"))
        == "payment.reversed"
    )
    assert (
        consumer.notification_code(event("payment.reversed", status="BOUNCED")) == "payment.bounced"
    )
    assert (
        consumer.notification_code(event("backorder.cancelled", by="staff"))
        == "backorder.cancelled"
    )
    assert (
        consumer.notification_code(event("backorder.cancelled", by="retailer"))
        == "backorder.cancelled_by_shop"
    )
    assert (
        consumer.notification_code(event("backorder.repriced_cancelled"))
        == "backorder.cancelled_by_shop"
    )
    assert consumer.notification_code(event("order_confirmation.created")) is None
    assert consumer.notification_code(event("stock.alert_resolved")) is None


def test_dispatch_after_an_earlier_invoice_is_its_own_notification(world):
    from apps.orders.tests.helpers import settings

    settings(world["t"], invoicing__timing="ON_ACCEPTANCE")
    with world["run"]():
        invoice = ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "1"))
    assert invoice.issued_trigger == "ON_ACCEPTANCE"
    assert not rows(world, "order.dispatched")
    assert {n.channel for n in rows(world, "order.dispatched_after_invoice")} == {
        "IN_APP",
        "WHATSAPP",
    }


def test_tenant_rules_override_and_extend_the_defaults(world):
    with tenant_context(world["t"].pk):
        NotificationRule.objects.create(
            event_code="order.placed",
            recipient="SHOP",
            channels=["IN_APP"],
            is_enabled=False,
        )
        NotificationRule.objects.create(
            event_code="order.placed",
            recipient="STAFF_PERMISSION",
            permission="stock.inward",
            channels=["IN_APP", "EMAIL"],
        )
    with world["run"]():
        place(world["t"], world["shop"], (world["product"], "1"))
    assert who(rows(world, "order.placed")) == {
        (world["owner"].pk, "IN_APP"),
        (world["owner"].pk, "EMAIL"),  # also holds stock.inward: one row per channel
        (world["warehouse"].pk, "IN_APP"),
        (world["warehouse"].pk, "EMAIL"),
        (world["sales"].pk, "IN_APP"),
    }  # the shop's rule is switched off


def test_tenant_templates_are_used_and_only_substitute_variables(world):
    with tenant_context(world["t"].pk):
        NotificationTemplate.objects.create(
            event_code="order.placed",
            audience="STAFF",  # the office's words: the owner's message, not the shop's
            channel="IN_APP",
            subject="Order {{order_number}} {% if 1 %}x{% endif %}",
            body="{{ shop }} {{ secret_key }} {{ order.__class__ }} {{ total|safe }}",
        )
    with world["run"]():
        order = place(world["t"], world["shop"], (world["product"], "1"))
    row = next(n for n in rows(world, "order.placed") if n.recipient_id == world["owner"].pk)
    assert row.title == f"Order {order.number} {{% if 1 %}}x{{% endif %}}"
    assert row.body == f"{world['shop'].shop_name}  {{{{ order.__class__ }}}} {{{{ total|safe }}}}"
    shop = next(n for n in rows(world, "order.placed") if n.recipient_id == world["login"].pk)
    assert shop.title == f"Order {order.number} placed"  # the shop's words are untouched


def test_another_tenants_people_get_nothing(world, tenant_b):
    other_owner = make_staff_in(tenant_b, "OWNER")
    with world["run"]():
        place(world["t"], world["shop"], (world["product"], "1"))
    with tenant_context(tenant_b.pk):
        assert not Notification.objects.exists()
    assert other_owner.pk not in {n.recipient_id for n in rows(world, "order.placed")}


def test_messages_name_products_not_codes(world):
    from apps.orders import fulfilment
    from apps.orders.models import Fulfilment, FulfilmentLine

    with world["run"]():
        order = place(world["t"], world["shop"], (world["product"], "3"))
    with world["run"](), tenant_context(world["t"].pk):
        transitions.accept_order(order.pk, by=world["owner"])
        shipment = Fulfilment.objects.get(order=order)
        line = FulfilmentLine.objects.get(fulfilment=shipment)
        fulfilment.pack(shipment.pk, {line.pk: D("1")}, by=world["owner"])
    [short] = rows(world, "order.short_supplied")[:1]
    assert "Product P-1 2 short" in short.body and "P-1 2 short" not in short.body.replace(
        "Product P-1", ""
    )
