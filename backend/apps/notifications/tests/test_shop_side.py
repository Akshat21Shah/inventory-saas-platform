"""The shop's side (ADR-048 items 5, 7, 15, 16): WhatsApp consent from the app, staff (confirmed)
and imports, opting out stopping waiting messages; preferences (in-app and compulsory locked);
announcements sent once when they start, by WhatsApp only when asked and agreed; the welcome
SMS through the notification log; account emails through the email adapter."""

from datetime import timedelta
from typing import Any

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts.adapters.sms import MockSmsSender
from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.dataio.kinds.retailers import RetailersKind
from apps.notifications import announcements, consent, preferences, quiet
from apps.notifications.adapters.whatsapp import MockWhatsAppClient
from apps.notifications.announcements import AnnouncementInput
from apps.notifications.models import Notification
from apps.orders.tests.helpers import make_shop, shop_user
from apps.platform import selectors
from apps.platform.models import FeatureFlag, TenantFeature
from apps.retailers.models import Retailer
from common.errors import InvalidFields
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
Source = consent.Source


@pytest.fixture(autouse=True)
def _mocks(monkeypatch):
    MockWhatsAppClient.outbox.clear()
    MockSmsSender.outbox.clear()
    monkeypatch.setattr(quiet, "current_hold", lambda now: None)  # tests run at any hour


@pytest.fixture
def world(tenant_a, django_capture_on_commit_callbacks):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    with tenant_context(tenant_a.pk):
        TenantFeature.objects.create(flag=FeatureFlag.objects.get(code="whatsapp"), enabled=True)
    selectors.invalidate_tenant_features(tenant_a.pk)
    return {
        "t": tenant_a,
        "owner": owner,
        "shop": shop,
        "login": shop_user(shop),
        "run": lambda: django_capture_on_commit_callbacks(execute=True),
    }


def fresh(world: dict[str, Any]) -> Retailer:
    with tenant_context(world["t"].pk):
        shop: Retailer = Retailer.objects.get(pk=world["shop"].pk)
        return shop


def test_consent_from_the_app_staff_and_import(world):
    with tenant_context(world["t"].pk):
        assert consent.should_prompt(world["shop"])
        consent.mark_prompted(world["shop"].pk)
        assert not consent.should_prompt(fresh(world))
        consent.set_whatsapp_consent(
            world["shop"].pk, True, source=Source.SHOP_APP, by=world["login"]
        )
    shop = fresh(world)
    assert shop.whatsapp_opt_in and shop.whatsapp_opt_in_source == "SHOP_APP"
    assert shop.whatsapp_opt_in_at is not None
    with tenant_context(world["t"].pk):
        consent.set_whatsapp_consent(
            world["shop"].pk, False, source=Source.STAFF, by=world["owner"]
        )
        with pytest.raises(InvalidFields) as unconfirmed:
            consent.set_whatsapp_consent(
                world["shop"].pk, True, source=Source.STAFF, by=world["owner"]
            )
        assert "whatsapp_consent_confirmed" in unconfirmed.value.details["fields"]
        consent.set_whatsapp_consent(
            world["shop"].pk, True, source=Source.STAFF, by=world["owner"], confirmed=True
        )
        assert consent.opted_in_count() == {"opted_in": 1, "shops": 1}
        actions = list(
            AuditLog.objects.filter(action__startswith="retailers.whatsapp").values_list(
                "action", flat=True
            )
        )
    assert sorted(actions) == [
        "retailers.whatsapp_opted_in",
        "retailers.whatsapp_opted_in",
        "retailers.whatsapp_opted_out",
    ]
    assert fresh(world).whatsapp_opt_in_source == "STAFF"


def test_the_import_column_records_consent(world):
    from apps.dataio.parsing import Row, Sheet

    kind = RetailersKind()
    sheet = Sheet(
        columns=["mobile", "whatsapp_opt_in"],
        ignored=[],
        rows=[Row(2, {"mobile": world["shop"].mobile[-10:], "whatsapp_opt_in": "Yes"})],
    )
    bad = Sheet(
        columns=["mobile", "whatsapp_opt_in"],
        ignored=[],
        rows=[Row(2, {"mobile": world["shop"].mobile[-10:], "whatsapp_opt_in": "maybe"})],
    )
    with tenant_context(world["t"].pk):
        [wrong] = kind.plan(bad, "ADD_OR_UPDATE", world["owner"])
        assert not wrong.ok
        [plan] = kind.plan(sheet, "ADD_OR_UPDATE", world["owner"])
        assert (plan.action, plan.changes) == (
            "UPDATE",
            {"WhatsApp consent": ["No", "Yes"]},
        )
        kind.apply(plan, by=world["owner"], cache={})
    shop = fresh(world)
    assert shop.whatsapp_opt_in and shop.whatsapp_opt_in_source == "IMPORT"


def test_opting_out_stops_waiting_whatsapp_messages(world):
    with tenant_context(world["t"].pk):
        consent.set_whatsapp_consent(world["shop"].pk, True, source=Source.SHOP_APP, by=None)
        waiting = Notification.objects.create(
            event_id=world["shop"].pk,
            event_code="payment.reminder",
            recipient=world["login"],
            retailer=world["shop"],
            channel="WHATSAPP",
            address=world["shop"].mobile,
            title="Reminder",
            body="…",
            send_after=timezone.now() + timedelta(hours=8),  # quiet hours
        )
        consent.set_whatsapp_consent(world["shop"].pk, False, source=Source.SHOP_APP, by=None)
        waiting.refresh_from_db()
    assert (waiting.status, waiting.skip_reason) == ("SKIPPED", "NO_WHATSAPP_OPT_IN")


def test_preferences_lock_in_app_and_compulsory_messages(world):
    with tenant_context(world["t"].pk):
        rows = {r["event"]: r for r in preferences.settings_for(world["login"], shop=True)}
        invoice = {c["channel"]: c for c in rows["invoice.issued"]["channels"]}
        accepted = {c["channel"]: c for c in rows["order.accepted"]["channels"]}
        assert rows["invoice.issued"]["compulsory"] and invoice["WHATSAPP"]["locked"]
        assert accepted["IN_APP"]["locked"] and not accepted["WHATSAPP"]["locked"]
        assert "order.cancelled_by_shop" not in rows  # staff-only
        preferences.set_preference(world["login"], "order.accepted", "WHATSAPP", False, shop=True)
        for event, channel in (
            ("order.accepted", "IN_APP"),
            ("invoice.issued", "WHATSAPP"),
            ("order.cancelled_by_shop", "IN_APP"),
        ):
            with pytest.raises(InvalidFields):
                preferences.set_preference(world["login"], event, channel, False, shop=True)
        rows = {r["event"]: r for r in preferences.settings_for(world["login"], shop=True)}
        accepted = {c["channel"]: c["enabled"] for c in rows["order.accepted"]["channels"]}
        assert accepted == {"IN_APP": True, "WHATSAPP": False}
        staff = {r["event"] for r in preferences.settings_for(world["owner"], shop=False)}
        assert {"order.placed", "order.cancelled_by_shop", "tax.rate_change_upcoming"} <= staff
        assert "invoice.issued" not in staff


def test_announcements_go_out_once_when_they_start(world):
    other = make_shop(world["t"], "9876500077")
    with tenant_context(world["t"].pk):
        consent.set_whatsapp_consent(world["shop"].pk, True, source=Source.SHOP_APP, by=None)
        with pytest.raises(InvalidFields):
            announcements.save(AnnouncementInput("", "x", timezone.now()), by=world["owner"])
        later = announcements.save(
            AnnouncementInput("Stock-taking", "Closed Sunday", timezone.now() + timedelta(days=1)),
            by=world["owner"],
        )
        now = announcements.save(
            AnnouncementInput(
                "Diwali timings",
                "Orders after 2 PM go the next day.",
                timezone.now() - timedelta(minutes=1),
                send_whatsapp=True,
            ),
            by=world["owner"],
        )
        assert list(announcements.showing()) == [now]
    with world["run"](), tenant_context(world["t"].pk):
        assert announcements.publish_due() == 1
        assert announcements.publish_due() == 0  # once
    with tenant_context(world["t"].pk):
        now.refresh_from_db()
        later.refresh_from_db()
        found = list(
            Notification.objects.filter(event_code="announcement.published").values_list(
                "retailer_id", "channel", "status", "skip_reason"
            )
        )
    assert now.published_at is not None and later.published_at is None
    assert sorted(found, key=str) == sorted(
        [
            (world["shop"].pk, "IN_APP", "SENT", ""),
            (world["shop"].pk, "WHATSAPP", "SENT", ""),
            (other.pk, "IN_APP", "SENT", ""),
            (other.pk, "WHATSAPP", "SKIPPED", "NO_WHATSAPP_OPT_IN"),
        ],
        key=str,
    )
    [sent] = MockWhatsAppClient.outbox
    assert sent.message.category == "MARKETING"
    assert sent.message.text.startswith(f"{world['t'].name}: Diwali timings")


def test_the_welcome_sms_is_logged_like_any_message(world):
    from apps.retailers.services import create_retailer

    with world["run"](), tenant_context(world["t"].pk):
        shop = create_retailer(shop_name="Laxmi Stores", phone="9876500066")
    [sms] = MockSmsSender.outbox
    assert sms.template == "retailer_welcome" and sms.phone == shop.mobile
    assert sms.text.startswith(f"{world['t'].name}: welcome, Laxmi Stores!")
    assert "alpha.localhost/shop/login" in sms.text
    with tenant_context(world["t"].pk):
        [row] = Notification.objects.filter(event_code="retailer.welcome")
        assert (row.channel, row.status, row.attempts) == ("SMS", "SENT", 1)
        assert Retailer.objects.get(pk=shop.pk).welcome_sent_at is not None


def test_account_emails_use_the_email_adapter(world):
    from apps.accounts.tasks import send_password_reset_email

    send_password_reset_email(str(world["owner"].pk))
    [email] = mail.outbox
    assert email.to == [world["owner"].email] and email.subject == "Reset your password"
