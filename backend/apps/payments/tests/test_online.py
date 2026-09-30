"""Shops paying online (ADR-049 items 9 and 10) with the mock gateway: a bill, everything owed or
a chosen amount; confirmed only by the signed webhook (never by the page), each event and each
gateway payment once; recorded through the normal payment flow; one active checkout per target
(reused, replaced when stale or when the amount changed and it was never opened); a different
amount flagged for review; advances off keeping an excess as credit; reconciliation catching a
missed webhook and expiring stale checkouts; reversal; the module, the gateway and idempotency;
the dev test-gateway page; the office's view; and other businesses."""

import json
from datetime import timedelta
from decimal import Decimal as D
from typing import Any
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.billing.models import Invoice
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.ledger.tests.helpers import check_ledger
from apps.notifications import quiet
from apps.orders.tests.helpers import add_stock, client_for, make_shop, settings, shop_client
from apps.payments import tasks
from apps.payments.gateway.base import GatewayKeys
from apps.payments.gateway.mock import EVENT_ID, SIGNATURE, MockGateway
from apps.payments.models import GatewayConfig, Payment, PaymentIntent, WebhookEvent
from apps.payments.tests.test_gateway import payments_on
from apps.retailers.models import Retailer
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"
KEYS = GatewayKeys("MOCK", "TEST", "mock_key_1", "secret-1", "hook-1")


def connect(tenant: Any, keys: GatewayKeys = KEYS, status: str = "VERIFIED") -> None:
    payments_on(tenant)
    with tenant_context(tenant.pk):
        GatewayConfig.objects.update_or_create(
            defaults={
                "provider": keys.provider,
                "mode": keys.mode,
                "key_id": keys.key_id,
                "key_secret": keys.key_secret,
                "webhook_secret": keys.webhook_secret,
                "status": status,
            }
        )


@pytest.fixture(autouse=True)
def _daytime(monkeypatch):
    monkeypatch.setattr(quiet, "current_hold", lambda now: None)


@pytest.fixture
def world(tenant_a, tenant_b, django_capture_on_commit_callbacks):
    connect(tenant_a)
    owner = make_staff_in(tenant_a, "OWNER")
    product = make_product(tenant_a, "P-1", base_price=D("100"))
    add_stock(tenant_a, product, "100")
    shop = make_shop(tenant_a, email="shop@example.com")
    run = django_capture_on_commit_callbacks
    with run(execute=True):
        bill = ship_invoice(tenant_a, shop, owner, (product, "2"))  # ₹210
    return {
        "t": tenant_a,
        "tb": tenant_b,
        "owner": owner,
        "product": product,
        "shop": shop,
        "bill": bill,
        "shop_api": shop_client(tenant_a, shop),
        "staff": client_for(tenant_a, owner),
        "sales": client_for(tenant_a, make_staff_in(tenant_a, "SALES")),
        "run": lambda: run(execute=True),
    }


def checkout(world: dict[str, Any], client: Any = None, **body: Any) -> Any:
    body = {"purpose": "INVOICE", "invoice_id": str(world["bill"].pk), **body}
    return (client or world["shop_api"]).post(
        f"{API}/shop/payments/checkout/",
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"k{uuid4().hex}",
    )


def webhook(world: dict[str, Any], payload: bytes, headers: dict[str, str], token: str = "") -> Any:
    from rest_framework.test import APIClient

    extra: dict[str, Any] = {
        f"HTTP_{name.upper().replace('-', '_')}": value for name, value in headers.items()
    }
    with world["run"]():
        return APIClient().post(
            f"{API}/webhooks/payments/mock/{token or world['t'].webhook_token}/",
            data=payload,
            content_type="application/json",
            **extra,
        )


def pay(world: dict[str, Any], order_id: str, **options: Any) -> Any:
    payload, headers = MockGateway.simulate(KEYS, order_id, **options)
    return webhook(world, payload, headers)


def intent(world: dict[str, Any], intent_id: str) -> PaymentIntent:
    with tenant_context(world["t"].pk):
        found: PaymentIntent = PaymentIntent.objects.get(pk=intent_id)
        return found


def online_payments(world: dict[str, Any]) -> list[Payment]:
    with tenant_context(world["t"].pk):
        return list(Payment.objects.filter(mode="ONLINE").order_by("created_at"))


@covers("shop-checkout", "shop-checkout-detail", "payment-webhook")
def test_a_shop_pays_a_bill_online(world):
    started = checkout(world)
    assert started.status_code == 200
    body = started.json()
    assert (body["status"], body["amount"], body["purpose"]) == ("CREATED", "210.00", "INVOICE")
    assert (
        body["checkout"]["checkout_url"]
        == f"/api/v1/dev/mock-gateway/{body['checkout']['order_id']}/"
    )
    assert "hook-1" not in json.dumps(body) and "secret-1" not in json.dumps(body)
    answer = pay(world, body["checkout"]["order_id"])
    assert (answer.status_code, answer.content) == (200, b"captured")
    [payment] = online_payments(world)
    assert (payment.amount, payment.status, payment.gateway_provider) == (
        D("210.00"),
        "RECEIVED",
        "MOCK",
    )
    assert payment.notes.startswith("Paid online by")
    assert payment.reference_no == payment.gateway_payment_id
    assert not payment.needs_review
    with tenant_context(world["t"].pk):
        bill = Invoice.objects.get(pk=world["bill"].pk)
    assert (bill.payment_status, bill.balance_due) == ("PAID", 0)
    shown = world["shop_api"].get(f"{API}/shop/payments/checkout/{body['id']}/").json()
    assert (shown["status"], shown["receipt_number"]) == ("PAID", payment.number)
    check_ledger(world["t"])


def test_what_the_page_says_is_never_enough(world):
    body = checkout(world).json()
    noted = world["shop_api"].post(
        f"{API}/shop/payments/checkout/{body['id']}/", {"outcome": "success"}, format="json"
    )
    assert (noted.json()["status"], noted.json()["awaiting_confirmation"]) == ("ATTEMPTED", True)
    assert online_payments(world) == []


def test_a_second_tap_reuses_the_checkout(world):
    first = checkout(world).json()
    again = checkout(world).json()
    assert again["id"] == first["id"]
    assert again["checkout"]["order_id"] == first["checkout"]["order_id"]
    everything = checkout(world, purpose="OUTSTANDING", invoice_id=None).json()
    assert everything["id"] != first["id"]  # another target, its own checkout


def test_a_stale_checkout_expires_and_a_new_one_starts(world):
    first = checkout(world).json()
    with tenant_context(world["t"].pk):
        PaymentIntent.objects.filter(pk=first["id"]).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
    second = checkout(world).json()
    assert second["id"] != first["id"]
    assert intent(world, first["id"]).status == "EXPIRED"


def test_a_changed_amount_replaces_a_checkout_never_opened(world):
    first = checkout(world, purpose="OUTSTANDING", invoice_id=None).json()
    assert first["amount"] == "210.00"
    with world["run"]():
        ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "1"))
    second = checkout(world, purpose="OUTSTANDING", invoice_id=None).json()
    assert (second["amount"], intent(world, first["id"]).status) == ("315.00", "EXPIRED")
    world["shop_api"].post(
        f"{API}/shop/payments/checkout/{second['id']}/", {"outcome": "dismissed"}, format="json"
    )
    with world["run"]():
        ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "1"))
    third = checkout(world, purpose="OUTSTANDING", invoice_id=None).json()
    assert third["id"] == second["id"]  # opened (maybe being paid): never replaced


def test_a_replaced_checkout_that_was_paid_is_recorded_first(world):
    first = checkout(world).json()
    MockGateway.simulate(KEYS, first["checkout"]["order_id"])  # paid, webhook lost
    with tenant_context(world["t"].pk):
        PaymentIntent.objects.filter(pk=first["id"]).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
    again = checkout(world).json()
    assert (again["id"], again["status"]) == (first["id"], "PAID")  # paid after all
    assert intent(world, first["id"]).status == "PAID"
    assert len(online_payments(world)) == 1


def test_webhooks_are_checked_and_handled_once(world):
    order_id = checkout(world).json()["checkout"]["order_id"]
    payload, headers = MockGateway.simulate(KEYS, order_id)
    forged = webhook(world, payload.replace(b"21000", b"99"), headers)
    assert forged.status_code == 400
    assert webhook(world, payload, {**headers, SIGNATURE: "0" * 64}).status_code == 400
    assert online_payments(world) == []
    assert webhook(world, payload, headers).content == b"captured"
    assert webhook(world, payload, headers).content == b"duplicate"  # the same event again
    again = webhook(world, payload, {**headers, EVENT_ID: "evt_other"})  # same payment, new id
    assert again.content == b"duplicate"
    assert len(online_payments(world)) == 1
    with tenant_context(world["t"].pk):
        assert WebhookEvent.objects.count() == 2
    assert webhook(world, payload, headers, token="nope").status_code == 404
    connect(world["tb"], GatewayKeys("MOCK", "TEST", "mock_b", "s", "hook-b"))
    assert webhook(world, payload, headers, token=world["tb"].webhook_token).status_code == 400


def test_another_amount_is_recorded_and_flagged(world):
    body = checkout(world).json()
    pay(world, body["checkout"]["order_id"], amount_paise=20000)  # ₹200 of ₹210
    [payment] = online_payments(world)
    assert (payment.amount, payment.needs_review) == (D("200.00"), True)
    assert payment.review_reason == "Paid ₹200.00; the checkout was for ₹210.00."
    shown = world["staff"].get(f"{API}/payments/{payment.pk}/").json()
    assert (shown["needs_review"], shown["review_reason"]) == (True, payment.review_reason)
    shop_view = world["shop_api"].get(f"{API}/shop/payments/{payment.pk}/").json()
    assert "needs_review" not in shop_view
    listed = world["staff"].get(f"{API}/payments/?needs_review=true").json()["results"]
    assert [(r["id"], r["needs_review"]) for r in listed] == [(str(payment.pk), True)]
    shop_list = world["shop_api"].get(f"{API}/shop/payments/").json()["results"]
    assert "needs_review" not in shop_list[0]
    url = f"{API}/payments/{payment.pk}/review/"
    assert world["sales"].post(url, {}, format="json").status_code == 403
    reviewed = world["staff"].post(url, {"note": "Shop paid the rest in cash"}, format="json")
    assert reviewed.json()["needs_review"] is False
    assert AuditLog.objects.filter(action="payments.online_reviewed").count() == 1
    again = world["staff"].post(url, {}, format="json")
    assert again.status_code == 400
    assert world["staff"].get(f"{API}/payments/?needs_review=true").json()["results"] == []


def test_with_advances_off_an_excess_is_kept_as_credit(world):
    settings(world["t"], payments__hold_advances=False)
    refused = checkout(world, purpose="CUSTOM", invoice_id=None, amount="500.00")
    assert refused.json()["error"]["details"]["fields"] == {
        "amount": ["That's more than you owe right now."]
    }
    small = checkout(world, purpose="CUSTOM", invoice_id=None, amount="0.50")
    assert small.json()["error"]["details"]["fields"] == {
        "amount": ["Enter at least ₹1, in rupees and paise."]
    }
    body = checkout(world, purpose="CUSTOM", invoice_id=None, amount="100.00").json()
    pay(world, body["checkout"]["order_id"], amount_paise=30000)  # ₹300 though ₹210 owed
    [payment] = online_payments(world)
    assert payment.amount == D("300.00") and payment.needs_review
    shown = world["staff"].get(f"{API}/payments/{payment.pk}/").json()
    assert shown["held_as_credit_while_advances_off"] == "90.00"
    check_ledger(world["t"])


def test_a_failed_try_keeps_the_checkout_open(world):
    body = checkout(world).json()
    pay(world, body["checkout"]["order_id"], outcome="FAILED")
    failed = intent(world, body["id"])
    assert (failed.status, failed.last_error) == ("ATTEMPTED", "The payment was declined.")
    url = f"{API}/shop/payments/checkout/{body['id']}/"
    shown = world["shop_api"].get(url).json()
    assert (shown["awaiting_confirmation"], shown["last_error"]) == (
        False,  # the shop sees why, not "waiting for the bank"
        "The payment was declined.",
    )
    noted = world["shop_api"].post(url, {"outcome": "success"}, format="json").json()
    assert (noted["awaiting_confirmation"], noted["last_error"]) == (True, "")  # tried again
    pay(world, body["checkout"]["order_id"], outcome="FAILED")  # the gateway has the last word
    assert world["shop_api"].get(url).json()["awaiting_confirmation"] is False
    pay(world, body["checkout"]["order_id"])
    assert intent(world, body["id"]).status == "PAID"


def test_reconciliation_catches_a_missed_webhook_and_expires_the_rest(world):
    paid = checkout(world).json()
    MockGateway.simulate(KEYS, paid["checkout"]["order_id"])  # the webhook never arrives
    left = checkout(world, purpose="CUSTOM", invoice_id=None, amount="50.00").json()
    with tenant_context(world["t"].pk):
        PaymentIntent.objects.update(created_at=timezone.now() - timedelta(minutes=10))
        PaymentIntent.objects.filter(pk=left["id"]).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
    with world["run"]():
        done = tasks.reconcile_for_tenant.apply(kwargs={"tenant_id": str(world["t"].pk)}).get()
    assert done == {"asked": 2, "captured": 1, "expired": 1}
    assert intent(world, paid["id"]).status == "PAID"
    assert intent(world, left["id"]).status == "EXPIRED"
    assert len(online_payments(world)) == 1


def test_an_online_payment_entered_in_error_can_be_reversed(world):
    body = checkout(world).json()
    pay(world, body["checkout"]["order_id"])
    [payment] = online_payments(world)
    with world["run"]():
        reversed_ = world["staff"].post(
            f"{API}/payments/{payment.pk}/reverse/",
            {"reason": "Recorded twice"},
            format="json",
        )
    assert reversed_.status_code == 200
    assert reversed_.json()["status"] == "REVERSED"
    check_ledger(world["t"])


def test_checkout_needs_the_module_a_working_gateway_and_a_key(world):
    no_key = world["shop_api"].post(
        f"{API}/shop/payments/checkout/", {"purpose": "OUTSTANDING"}, format="json"
    )
    assert no_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    MockGateway.script("DOWN")
    down = checkout(world)
    assert (down.status_code, down.json()["error"]["code"]) == (503, "PAYMENT_GATEWAY_UNAVAILABLE")
    with tenant_context(world["t"].pk):
        assert not PaymentIntent.objects.exists()  # nothing half-made
    connect(world["t"], status="FAILED")
    assert checkout(world).json()["error"]["code"] == "PAYMENT_GATEWAY_NOT_READY"
    assert world["shop_api"].get(f"{API}/shop/account/").json()["online_payments"] is False
    connect(world["t"])
    assert world["shop_api"].get(f"{API}/shop/account/").json()["online_payments"] is True
    other_shop = make_shop(world["tb"], "9876500099")
    elsewhere = checkout(world, client=shop_client(world["tb"], other_shop))
    assert elsewhere.json()["error"]["code"] == "MODULE_NOT_ENABLED"


@covers("mock-gateway")
def test_the_dev_test_gateway_page(world, settings):
    from rest_framework.test import APIClient

    body = checkout(world).json()
    page_url = body["checkout"]["checkout_url"]
    browser = APIClient()
    host: dict[str, Any] = {"HTTP_X_FORWARDED_HOST": f"{world['t'].slug}.localhost"}
    page = browser.get(page_url, **host)
    assert page.status_code == 200 and "₹210.00" in page.content.decode()
    with world["run"]():
        paid = browser.post(
            page_url,
            "outcome=CAPTURED",
            content_type="application/x-www-form-urlencoded",
            **host,
        )
    assert paid.status_code == 200 and "Paid." in paid.content.decode()
    assert intent(world, body["id"]).status == "PAID"
    assert browser.get(page_url).status_code == 404  # no tenant host
    settings.ALLOW_MOCK_INTEGRATIONS = False
    assert browser.get(page_url, **host).status_code == 404


@covers("payment-intents", "payment-review")
def test_the_office_sees_checkouts_of_its_own_shops(world):
    body = checkout(world).json()
    rows = world["staff"].get(f"{API}/payment-intents/").json()["results"]
    assert [(r["id"], r["shop_name"], r["status"]) for r in rows] == [
        (body["id"], world["shop"].shop_name, "CREATED")
    ]
    assert world["staff"].get(f"{API}/payment-intents/?status=PAID").json()["results"] == []
    for term in (world["shop"].shop_name[:5], world["bill"].number, body["checkout"]["order_id"]):
        found = world["staff"].get(f"{API}/payment-intents/", {"search": term}).json()
        assert [r["id"] for r in found["results"]] == [body["id"]]
    assert world["staff"].get(f"{API}/payment-intents/?search=nobody").json()["results"] == []
    assert world["staff"].get(f"{API}/payment-intents/?status=NOPE").status_code == 400
    assert world["staff"].get(f"{API}/payment-intents/?retailer=abc").status_code == 400
    # Sales staff who see only their own shops see only those shops' checkouts.
    salesman = make_staff_in(world["t"], "SALES")
    settings(world["t"], orders__sales_visibility="ASSIGNED_RETAILERS")
    own = client_for(world["t"], salesman)
    assert own.get(f"{API}/payment-intents/").json()["results"] == []
    with tenant_context(world["t"].pk):
        Retailer.objects.filter(pk=world["shop"].pk).update(salesperson=salesman)
    assert [r["id"] for r in own.get(f"{API}/payment-intents/").json()["results"]] == [body["id"]]
    other = client_for(world["tb"], make_staff_in(world["tb"], "OWNER"))
    assert other.get(f"{API}/payment-intents/").json()["results"] == []
    other_shop = shop_client(world["tb"], make_shop(world["tb"], "9876500098"))
    assert other_shop.get(f"{API}/shop/payments/checkout/{body['id']}/").status_code == 404
    another_shop = shop_client(world["t"], make_shop(world["t"], "9876500097"))
    assert another_shop.get(f"{API}/shop/payments/checkout/{body['id']}/").status_code == 404


def test_a_slow_gateway_asks_the_shop_to_try_again_without_a_second_checkout(world):
    MockGateway.script("TIMEOUT")
    slow = checkout(world)
    assert (slow.status_code, slow.json()["error"]["code"]) == (503, "PAYMENT_GATEWAY_UNAVAILABLE")
    assert slow.json()["error"]["message"] == (
        "Payment service is busy, please try again in a minute."
    )
    with tenant_context(world["t"].pk):
        assert not PaymentIntent.objects.exists()
    first = checkout(world).json()
    with tenant_context(world["t"].pk):  # stale: before replacing it, the gateway is asked
        PaymentIntent.objects.filter(pk=first["id"]).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
    MockGateway.script("TIMEOUT")
    unsure = checkout(world)
    assert unsure.status_code == 503
    assert intent(world, first["id"]).status == "CREATED"  # kept: it may have been paid
    with tenant_context(world["t"].pk):
        assert PaymentIntent.objects.count() == 1
    replaced = checkout(world).json()  # the gateway answers: now it is replaced
    assert replaced["id"] != first["id"]
