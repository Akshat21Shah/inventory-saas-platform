"""Delivery (ADR-048): email, WhatsApp and SMS through their adapters (mocks here), every try
logged, retries with backoff then "Failed", a retry by hand, stale and lost rows picked up again,
the distributor's own WhatsApp number over the platform's, mocks refused in deployed settings,
and the in-app bell rung over the socket."""

import json
from datetime import timedelta
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from apps.accounts.adapters.sms import MockSmsSender
from apps.accounts.tests.factories import make_staff_in
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.notifications import delivery
from apps.notifications.adapters.base import DeliveryError, PermanentDeliveryError
from apps.notifications.adapters.whatsapp import MockWhatsAppClient, get_whatsapp_client
from apps.notifications.checks import notification_channels_check
from apps.notifications.models import DeliveryAttempt, Notification, WhatsAppSender
from apps.orders.tests.helpers import add_stock, make_shop, shop_user
from apps.platform import selectors
from apps.platform.models import FeatureFlag, TenantFeature
from apps.retailers.models import Retailer
from common.live import Grant, groups_for, user_group
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
S = Notification.Status


@pytest.fixture(autouse=True)
def _mocks():
    MockWhatsAppClient.outbox.clear()
    MockSmsSender.outbox.clear()
    yield
    MockWhatsAppClient.outbox.clear()
    MockSmsSender.outbox.clear()


@pytest.fixture
def world(tenant_a, django_capture_on_commit_callbacks):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a, email="shop@example.com")
    with tenant_context(tenant_a.pk):
        Retailer.objects.filter(pk=shop.pk).update(whatsapp_opt_in=True)
        TenantFeature.objects.create(flag=FeatureFlag.objects.get(code="whatsapp"), enabled=True)
    selectors.invalidate_tenant_features(tenant_a.pk)
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


def sent_whatsapp(template: str = "b2b_invoice_issued") -> list[Any]:
    return [m for m in MockWhatsAppClient.outbox if m.message.template == template]


def invoice(world: dict[str, Any]) -> Any:
    with world["run"]():
        return ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "2"))


def row(world: dict[str, Any], channel: str, code: str = "invoice.issued") -> Notification:
    with tenant_context(world["t"].pk):
        found: Notification = Notification.objects.get(event_code=code, channel=channel)
        return found


def attempts(world: dict[str, Any], n: Notification) -> list[DeliveryAttempt]:
    with tenant_context(world["t"].pk):
        return list(DeliveryAttempt.objects.filter(notification=n).order_by("attempt_no"))


def deliver(world: dict[str, Any], n: Notification) -> str:
    with tenant_context(world["t"].pk):
        return delivery.deliver(n.pk)


def make_due(world: dict[str, Any], n: Notification) -> None:
    with tenant_context(world["t"].pk):
        Notification.objects.filter(pk=n.pk).update(send_after=timezone.now() - timedelta(1))


def test_an_invoice_reaches_the_shop_by_email_and_whatsapp(world):
    bill = invoice(world)
    email, whatsapp = row(world, "EMAIL"), row(world, "WHATSAPP")
    assert (email.status, whatsapp.status) == (S.SENT, S.SENT)
    [sent] = [m for m in mail.outbox if m.to == ["shop@example.com"]]
    assert sent.from_email.startswith(f"{world['t'].name} <")
    assert sent.reply_to == [world["t"].email]
    assert bill.number in sent.subject and bill.number in sent.body
    [message] = sent_whatsapp()
    assert message.message.to == world["shop"].mobile
    assert message.message.template == "b2b_invoice_issued"
    assert message.message.parameters[0] == world["t"].name
    assert message.sender.own_number is False  # the platform's number
    [attempt] = attempts(world, whatsapp)
    assert (attempt.attempt_no, attempt.status, attempt.provider) == (1, "SENT", "whatsapp-mock")
    assert whatsapp.provider_message_id.startswith("mock-") and whatsapp.attempts == 1


def test_the_distributors_own_number_is_used_once_connected(world):
    with tenant_context(world["t"].pk):
        WhatsAppSender.objects.create(
            provider="mock",
            phone_number="+919800000001",
            display_name="Sharma Distributors",
            credentials=json.dumps({"token": "t"}),
            is_active=True,
        )
    invoice(world)
    [message] = sent_whatsapp()
    assert message.sender.own_number and message.sender.phone_number == "+919800000001"
    assert message.sender.credentials == {"token": "t"}


def test_failures_are_retried_with_backoff_then_failed_and_can_be_retried(world, monkeypatch):
    def broken(self, message, sender):
        raise DeliveryError("provider timeout")

    monkeypatch.setattr(MockWhatsAppClient, "send_template", broken)
    invoice(world)
    n = row(world, "WHATSAPP")
    assert (n.status, n.attempts, n.last_error) == (S.PENDING, 1, "provider timeout")
    assert n.send_after is not None
    assert timedelta(seconds=50) < n.send_after - timezone.now() <= timedelta(minutes=1)
    assert deliver(world, n) == ""  # not due yet
    waits = []
    for _ in range(5):
        make_due(world, n)
        before = timezone.now()
        deliver(world, n)
        n = row(world, "WHATSAPP")
        if n.status == S.PENDING and n.send_after is not None:
            waits.append(round((n.send_after - before).total_seconds() / 60))
    assert waits == [2, 4, 8, 16]
    assert (n.status, n.attempts) == (S.FAILED, 6)
    assert [a.status for a in attempts(world, n)] == ["FAILED"] * 6
    with tenant_context(world["t"].pk):
        assert delivery.due() == []  # failed rows wait for a person
    monkeypatch.undo()
    with world["run"](), tenant_context(world["t"].pk):
        assert delivery.retry(n.pk)
    n = row(world, "WHATSAPP")
    assert (n.status, n.attempts, n.last_error) == (S.SENT, 7, "")
    assert [a.attempt_no for a in attempts(world, n)] == [1, 2, 3, 4, 5, 6, 7]
    with tenant_context(world["t"].pk):
        assert not delivery.retry(n.pk)  # only failed rows


def test_a_permanent_error_fails_at_once(world, monkeypatch):
    def refused(self, message, sender):
        raise PermanentDeliveryError("number not on WhatsApp")

    monkeypatch.setattr(MockWhatsAppClient, "send_template", refused)
    invoice(world)
    n = row(world, "WHATSAPP")
    assert (n.status, n.attempts, n.last_error) == (S.FAILED, 1, "number not on WhatsApp")


def test_stale_and_lost_rows_are_sent_by_the_sweeper(world, monkeypatch):
    monkeypatch.setattr(delivery, "enqueue", lambda ids: None)  # every enqueue is "lost"
    invoice(world)
    email, whatsapp, in_app = row(world, "EMAIL"), row(world, "WHATSAPP"), row(world, "IN_APP")
    assert (email.status, in_app.status) == (S.PENDING, S.SENT)
    old = timezone.now() - timedelta(minutes=15)
    with tenant_context(world["t"].pk):
        assert delivery.due() == []  # just created: its enqueue may still arrive
        Notification.objects.filter(pk=email.pk).update(created_at=old)
        Notification.objects.filter(pk=whatsapp.pk).update(status=S.SENDING, updated_at=old)
        found = delivery.due()
    assert set(found) == {email.pk, whatsapp.pk}
    assert row(world, "WHATSAPP").status == S.PENDING  # a worker died mid-send: tried again
    assert deliver(world, email) == S.SENT


def test_a_row_being_sent_is_not_sent_twice(world, monkeypatch):
    monkeypatch.setattr(delivery, "enqueue", lambda ids: None)
    invoice(world)
    n = row(world, "WHATSAPP")
    with tenant_context(world["t"].pk):
        Notification.objects.filter(pk=n.pk).update(status=S.SENDING)
    assert deliver(world, n) == ""
    assert sent_whatsapp() == []


def test_sms_goes_through_the_sms_adapter(world):
    with tenant_context(world["t"].pk):
        n = Notification.objects.create(
            event_id=world["shop"].pk,
            event_code="retailer.welcome",
            recipient=world["login"],
            retailer=world["shop"],
            channel="SMS",
            address=world["shop"].mobile,
            title="Welcome",
            body=f"{world['t'].name}: welcome",
            data={"whatsapp": None},
        )
    assert deliver(world, n) == S.SENT
    [sms] = MockSmsSender.outbox
    assert (sms.phone, sms.text, sms.template) == (
        world["shop"].mobile,
        f"{world['t'].name}: welcome",
        "retailer.welcome",
    )


def test_mocks_are_refused_in_deployed_settings(settings):
    settings.ALLOW_MOCK_INTEGRATIONS = True
    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    assert notification_channels_check(None) == []
    settings.ALLOW_MOCK_INTEGRATIONS = False
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    assert {e.id for e in notification_channels_check(None)} == {
        "notifications.E001",
        "notifications.E002",
    }
    with pytest.raises(ImproperlyConfigured):
        get_whatsapp_client("mock")


def test_everyone_joins_their_own_bell_group():
    staff = Grant("u1", "t1", orders=True)
    assert groups_for(staff) == ["orders.t1", user_group("t1", "u1")]
    assert groups_for(Grant("u2", "t1")) == [user_group("t1", "u2")]
    assert groups_for(Grant("u3", "t1", retailer_id="r1")) == ["shop.r1", "user.t1.u3"]


def test_the_bell_rings_for_the_people_notified(world, tenant_b, monkeypatch):
    from apps.orders.tests.test_live import Socket

    async def keep() -> None:
        return None

    monkeypatch.setattr("channels.consumer.aclose_old_connections", keep)
    from common.live import issue_ticket

    t = str(world["t"].pk)
    tickets = {
        "shop": issue_ticket(Grant(str(world["login"].pk), t, retailer_id=str(world["shop"].pk))),
        "owner": issue_ticket(Grant(str(world["owner"].pk), t, orders=True)),
        "same_user_other_tenant": issue_ticket(Grant(str(world["login"].pk), str(tenant_b.pk))),
    }

    async def run() -> dict[str, list[Any]]:
        sockets = {}
        for name, ticket in tickets.items():
            socket = Socket(ticket)
            assert (await socket.connect())[0]
            await socket.receive_json_from()  # ready
            sockets[name] = socket
        from asgiref.sync import sync_to_async

        await sync_to_async(delivery.push_in_app)(world["t"].pk, [world["login"].pk])
        heard: dict[str, list[Any]] = {}
        for name, socket in sockets.items():
            heard[name] = []
            while not await socket.receive_nothing(timeout=0.05):
                heard[name].append(await socket.receive_json_from())
            await socket.disconnect()
        return heard

    heard = async_to_sync(run)()
    assert heard == {"shop": [{"type": "notification"}], "owner": [], "same_user_other_tenant": []}


def test_a_fan_out_rings_the_bells_after_commit(world, monkeypatch):
    rung: list[tuple[Any, set[Any]]] = []
    monkeypatch.setattr(delivery, "push_in_app", lambda t, users: rung.append((t, set(users))))
    invoice(world)
    shop_bells = [users for _, users in rung if world["login"].pk in users]
    assert shop_bells and all(t == world["t"].pk for t, _ in rung)
