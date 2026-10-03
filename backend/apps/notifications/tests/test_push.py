"""App notifications to the Android shop app (ADR-061 item 7; owner, §10.2q answers 1 to 3): phones,
the rules, what reaches the lock screen, preferences, quiet hours, the shop's language, sending
to each phone, and the FCM adapter's handling of its answers."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from typing import Any

import jwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from apps.accounts.tests.factories import make_retailer_login, make_staff_in
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.notifications import delivery, devices, push, quiet
from apps.notifications.adapters.base import DeliveryError, PermanentDeliveryError
from apps.notifications.adapters.push import (
    FcmPushSender,
    MockPushSender,
    PushMessage,
    UnregisteredDevice,
)
from apps.notifications.catalog import EVENTS
from apps.notifications.checks import notification_channels_check
from apps.notifications.models import DeviceToken, Notification, NotificationPreference
from apps.orders.tests.helpers import add_stock, make_shop, place, shop_user
from apps.platform import selectors
from apps.platform.models import FeatureFlag, TenantFeature
from apps.retailers.models import Retailer
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
DETAILS = "Open the app to see the details."


@pytest.fixture(autouse=True)
def _clean():
    MockPushSender.outbox.clear()
    MockPushSender.unregistered.clear()
    cache.clear()
    yield
    MockPushSender.outbox.clear()
    MockPushSender.unregistered.clear()
    cache.clear()


@pytest.fixture
def world(tenant_a, django_capture_on_commit_callbacks):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a, email="shop@example.com")
    product = make_product(tenant_a, "P-1")
    add_stock(tenant_a, product, "100")
    return {
        "t": tenant_a,
        "owner": owner,
        "shop": shop,
        "login": shop_user(shop),
        "product": product,
        "run": lambda: django_capture_on_commit_callbacks(execute=True),
    }


def phone(world: dict[str, Any], token: str = "tok-1") -> None:  # noqa: S107
    with tenant_context(world["t"].pk):
        devices.register_device(world["login"], token, "ANDROID", "1.0.0")


def rows(world: dict[str, Any], code: str, channel: str) -> list[Notification]:
    with tenant_context(world["t"].pk):
        return list(Notification.objects.filter(event_code=code, channel=channel))


def whatsapp_for(world: dict[str, Any]) -> None:
    with tenant_context(world["t"].pk):
        TenantFeature.objects.create(flag=FeatureFlag.objects.get(code="whatsapp"), enabled=True)
        Retailer.objects.filter(pk=world["shop"].pk).update(whatsapp_opt_in=True)
    selectors.invalidate_tenant_features(world["t"].pk)


# --- Phones ---------------------------------------------------------------------------------


@covers("shop-device", "shop-device-remove")
def test_a_shop_registers_and_removes_its_phone(tenant_a, tenant_b, api_client_for):
    login_a = make_retailer_login(tenant_a, "9876543210")
    login_b = make_retailer_login(tenant_b, "9876543210")
    shop_a, shop_b = api_client_for(login_a, tenant_a), api_client_for(login_b, tenant_b)
    body = {"token": "same-phone", "platform": "ANDROID", "app_version": "1.0.0"}
    assert shop_a.post("/api/v1/shop/devices/", body, format="json").status_code == 204
    assert shop_a.post("/api/v1/shop/devices/", body, format="json").status_code == 204  # again
    # The same phone signed in to another distributor: a row of its own there.
    assert shop_b.post("/api/v1/shop/devices/", body, format="json").status_code == 204
    with tenant_context(tenant_a.pk):
        assert list(DeviceToken.objects.values_list("user_id", "app_version")) == [
            (login_a.pk, "1.0.0")
        ]
    removed = shop_b.post("/api/v1/shop/devices/remove/", {"token": "same-phone"}, format="json")
    assert removed.status_code == 204
    with tenant_context(tenant_b.pk):
        assert not DeviceToken.objects.exists()
    with tenant_context(tenant_a.pk):
        assert DeviceToken.objects.count() == 1  # the other distributor's row is untouched
    staff = api_client_for(make_staff_in(tenant_a, "OWNER"), tenant_a)
    assert staff.post("/api/v1/shop/devices/", body, format="json").status_code == 403
    bad = shop_a.post("/api/v1/shop/devices/", {**body, "app_version": "1.0"}, format="json")
    assert bad.status_code == 400


# --- Who gets a push, and what it says --------------------------------------------------------


def test_only_a_shop_with_the_app_gets_a_push(world):
    with world["run"]():
        place(world["t"], world["shop"], (world["product"], "2"))
    assert rows(world, "order.placed", "PUSH") == []  # no phone: no row at all
    phone(world)
    with world["run"]():
        order = place(world["t"], world["shop"], (world["product"], "1"))
    [row] = rows(world, "order.placed", "PUSH")
    assert row.recipient_id == world["login"].pk and row.status == "SENT"
    assert row.title == f"Order {order.number} placed"
    # The in-app words carry the total; nothing goes by SMS or WhatsApp: no amount here.
    assert row.body == DETAILS
    assert row.data["path"] == f"/shop/orders/{order.pk}" and row.data["tenant"] == "alpha"
    [in_app] = [
        r for r in rows(world, "order.placed", "IN_APP") if r.data["path"] == row.data["path"]
    ]
    assert row.data["in_app_id"] == str(in_app.pk)
    [sent] = MockPushSender.outbox
    assert (sent.token, sent.title, sent.body) == ("tok-1", row.title, DETAILS)
    assert sent.data == {
        "path": f"/shop/orders/{order.pk}",
        "notification": str(in_app.pk),
        "tenant": "alpha",
        "event": "order.placed",
    }
    # Staff never get pushes (the app is the shop's).
    assert {r.recipient_id for r in rows(world, "order.placed", "PUSH")} == {world["login"].pk}


def test_a_bill_hides_its_amount_unless_whatsapp_already_shows_it(world):
    phone(world)
    with world["run"]():
        invoice = ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "2"))
    [row] = rows(world, "invoice.issued", "PUSH")
    assert row.title == f"New bill {invoice.number}" and row.body == DETAILS
    assert "₹" not in row.title + row.body

    whatsapp_for(world)
    with world["run"]():
        second = ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "1"))
    [row] = [r for r in rows(world, "invoice.issued", "PUSH") if second.number in r.title]
    assert row.title.startswith(f"Bill {second.number}: ₹") and "₹" in row.body


def test_the_delivery_code_never_reaches_the_lock_screen(tenant_a):
    values = {
        "order_number": "SO-1",
        "shipment": "SO-1/1",
        "vehicle": "",
        "delivery_code": " Delivery code: 4321.",
        "distributor": "Alpha",
    }
    with tenant_context(tenant_a.pk):
        text = push.lock_screen_text("order.dispatched", values, "en", amounts_allowed=True)
    assert text is not None
    assert (text["title"], text["body"]) == (
        "Order SO-1 is on its way",
        "Shipment SO-1/1 of order SO-1 left the warehouse.",
    )


def test_no_event_puts_any_other_code_in_a_push():
    """A new shop message with a code in it must be added to ``push.CODE_VARIABLES`` first."""
    from apps.notifications.catalog import EVENTS

    risky = {
        variable
        for event in EVENTS.values()
        if event.shop_facing
        for variable in event.variables
        if any(word in variable for word in ("code", "otp", "pin", "password"))
    }
    assert risky <= push.CODE_VARIABLES


def test_pushes_follow_the_shops_language(world, every_language):
    with tenant_context(world["t"].pk):
        Retailer.objects.filter(pk=world["shop"].pk).update(preferred_language="hi")
    phone(world)
    with world["run"]():
        invoice = ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "2"))
    [row] = rows(world, "invoice.issued", "PUSH")
    assert row.title == f"नया बिल {invoice.number}"
    assert row.body == "पूरी जानकारी के लिए ऐप खोलें।"


def test_a_shop_can_switch_pushes_off_except_compulsory_ones(world):
    phone(world)
    with tenant_context(world["t"].pk):
        for event in ("order.placed", "invoice.issued"):
            NotificationPreference.objects.create(
                user=world["login"], event_code=event, channel="PUSH", enabled=False
            )
    with world["run"]():
        ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "2"))
    [placed] = rows(world, "order.placed", "PUSH")
    assert (placed.status, placed.skip_reason) == ("SKIPPED", "TURNED_OFF")
    [bill] = rows(world, "invoice.issued", "PUSH")
    assert bill.status == "SENT"  # bills are compulsory: they can't be switched off


def test_non_urgent_pushes_wait_for_quiet_hours_to_end(world, monkeypatch):
    phone(world)
    morning = timezone.now() + timedelta(hours=9)
    monkeypatch.setattr(quiet, "current_hold", lambda now: morning)
    monkeypatch.setitem(EVENTS, "order.placed", replace(EVENTS["order.placed"], urgent=False))
    with world["run"]():
        place(world["t"], world["shop"], (world["product"], "1"))
    [row] = rows(world, "order.placed", "PUSH")
    assert row.status == "PENDING" and row.send_after == morning
    assert MockPushSender.outbox == []


# --- The rules ------------------------------------------------------------------------------


def test_the_app_notification_is_on_wherever_in_app_is_for_shops(world, api_client_for):
    staff = api_client_for(world["owner"], world["t"])
    matrix = staff.get("/api/v1/notification-rules/").json()
    shop_rules = [r for e in matrix["events"] for r in e["rules"] if r["recipient"] == "SHOP"]
    assert shop_rules
    for rule in shop_rules:
        assert ("PUSH" in rule["channels"]) == ("IN_APP" in rule["channels"]), rule
    turned_off = {"rules": [{"recipient": "SHOP", "channels": ["IN_APP"], "compulsory": True}]}
    saved = staff.put("/api/v1/notification-rules/invoice.issued/", turned_off, format="json")
    assert saved.status_code == 200, saved.json()
    phone(world)
    with world["run"]():
        ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "1"))
    assert rows(world, "invoice.issued", "PUSH") == []
    for_staff = {"rules": [{"recipient": "OWNERS", "channels": ["PUSH"]}]}
    refused = staff.put("/api/v1/notification-rules/invoice.issued/", for_staff, format="json")
    assert refused.status_code == 400


# --- Sending --------------------------------------------------------------------------------


def _push_row(world: dict[str, Any]) -> Notification:
    with world["run"]():
        place(world["t"], world["shop"], (world["product"], "1"))
    [row] = rows(world, "order.placed", "PUSH")
    return row


def test_a_push_goes_to_each_phone_and_forgets_removed_apps(world):
    phone(world, "old-phone")
    phone(world, "new-phone")
    MockPushSender.unregistered.add("old-phone")
    row = _push_row(world)
    assert row.status == "SENT"
    assert [m.token for m in MockPushSender.outbox] == ["new-phone"]
    with tenant_context(world["t"].pk):
        assert dict(DeviceToken.objects.values_list("token", "is_active")) == {
            "old-phone": False,
            "new-phone": True,
        }
        assert row.delivery_attempts.get().response == {"devices": 2, "sent": 1, "removed": 1}


def test_a_push_to_a_removed_app_fails_at_once(world):
    phone(world, "gone")
    MockPushSender.unregistered.add("gone")
    row = _push_row(world)
    with tenant_context(world["t"].pk):
        row.refresh_from_db()
        assert row.status == "FAILED" and row.attempts == 1
        assert not DeviceToken.objects.get().is_active


def test_a_busy_push_service_is_tried_again(world, monkeypatch):
    phone(world)

    def busy(self, message):
        raise DeliveryError("FCM busy: 503")

    monkeypatch.setattr(MockPushSender, "send", busy)
    row = _push_row(world)
    with tenant_context(world["t"].pk):
        row.refresh_from_db()
        assert row.status == "PENDING" and row.send_after is not None
        assert row.last_error == "FCM busy: 503"
    monkeypatch.undo()
    with tenant_context(world["t"].pk):
        Notification.objects.filter(pk=row.pk).update(send_after=timezone.now())
        assert delivery.deliver(row.pk) == "SENT"


# --- The FCM adapter (its handling of answers; the API itself is TODO(verify)) ---------------


class _Answer:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status_code, self._body = status, body
        self.ok = 200 <= status < 300

    def json(self) -> dict[str, Any]:
        return self._body


@pytest.fixture
def fcm(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    calls: list[tuple[str, dict[str, Any]]] = []
    answers: list[_Answer] = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/token"):
            claims = jwt.decode(
                kwargs["data"]["assertion"],
                key.public_key(),
                algorithms=["RS256"],
                audience="https://oauth2.googleapis.com/token",
            )
            assert claims["scope"] == FcmPushSender.SCOPE
            return _Answer(200, {"access_token": "access-1", "expires_in": 3600})
        return answers.pop(0)

    monkeypatch.setattr(requests, "post", post)
    sender = FcmPushSender(
        {"project_id": "shop-app", "client_email": "push@shop-app.iam", "private_key": pem}
    )
    return sender, calls, answers


def test_fcm_sends_and_signs_in_once(fcm):
    sender, calls, answers = fcm
    answers += [_Answer(200, {"name": "projects/shop-app/messages/1"})] * 2
    message = PushMessage("tok", "Title", "Body", {"path": "/shop"}, urgent=False)
    assert sender.send(message).message_id == "projects/shop-app/messages/1"
    sender.send(message)
    assert [url for url, _ in calls].count("https://oauth2.googleapis.com/token") == 1
    url, request = calls[1]
    assert url == "https://fcm.googleapis.com/v1/projects/shop-app/messages:send"
    assert request["headers"] == {"Authorization": "Bearer access-1"}
    assert request["json"]["message"] == {
        "token": "tok",
        "notification": {"title": "Title", "body": "Body"},
        "data": {"path": "/shop"},
        "android": {"priority": "NORMAL", "notification": {"channel_id": "messages"}},
    }


@pytest.mark.parametrize(
    ("status", "body", "raised"),
    [
        (404, {"error": {"status": "NOT_FOUND"}}, UnregisteredDevice),
        (
            400,
            {"error": {"status": "INVALID_ARGUMENT", "details": [{"errorCode": "UNREGISTERED"}]}},
            UnregisteredDevice,
        ),
        (503, {"error": {"status": "UNAVAILABLE"}}, DeliveryError),
        (429, {"error": {"status": "RESOURCE_EXHAUSTED"}}, DeliveryError),
        (401, {"error": {"status": "UNAUTHENTICATED"}}, DeliveryError),
        (400, {"error": {"status": "INVALID_ARGUMENT"}}, PermanentDeliveryError),
    ],
)
def test_fcm_answers(fcm, status, body, raised):
    sender, _, answers = fcm
    answers.append(_Answer(status, body))
    with pytest.raises(raised):
        sender.send(PushMessage("tok", "T", "B"))
    if raised is not UnregisteredDevice and raised is not PermanentDeliveryError:
        assert not issubclass(raised, PermanentDeliveryError)  # tried again with backoff


def test_a_deployment_needs_a_real_push_service():
    with override_settings(PUSH_PROVIDER="mock", ALLOW_MOCK_INTEGRATIONS=False):
        assert "notifications.E003" in {e.id for e in notification_channels_check(None)}
    with override_settings(PUSH_PROVIDER="fcm", FCM_SERVICE_ACCOUNT_JSON=""):
        assert "notifications.E004" in {e.id for e in notification_channels_check(None)}
    with override_settings(PUSH_PROVIDER="fcm", FCM_SERVICE_ACCOUNT_JSON='{"project_id": "x"}'):
        assert not {"notifications.E003", "notifications.E004"} & {
            e.id for e in notification_channels_check(None)
        }


def test_money_amounts_use_the_rupee_sign_the_push_rule_relies_on():
    from common.numbers import rupees

    assert push.has_amount(rupees(D("1234.5")))


def test_the_app_switch_shows_once_the_shop_has_the_app(world, api_client_for):
    shop = api_client_for(world["login"], world["t"])

    def channels() -> set[str]:
        rows = shop.get("/api/v1/shop/notification-preferences/").json()
        return {c["channel"] for row in rows for c in row["channels"]}

    assert "PUSH" not in channels()  # the web shop, no app: nothing to switch
    phone(world)
    assert "PUSH" in channels()
    off = {"event": "order.accepted", "channel": "PUSH", "enabled": False}
    assert shop.put("/api/v1/shop/notification-preferences/", off, format="json").status_code == 200
