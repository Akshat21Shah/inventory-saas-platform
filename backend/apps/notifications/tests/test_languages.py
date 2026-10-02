"""Messages in each person's language (ADR-060 item 5): every default text exists in Hindi and
Marathi with the English text's variables; a Hindi shop and Marathi staff get their own words,
values included ("नकद", "रोख"); a distributor's English edit doesn't replace the standard Hindi;
the Hindi and Marathi welcome SMS fit one Unicode part; previews use the text's language."""

import re
from decimal import Decimal as D
from typing import Any

import pytest
from django.utils import translation

from apps.accounts.models import User
from apps.accounts.tests.factories import make_staff_in
from apps.notifications import quiet, sms_length, texts
from apps.notifications.adapters.whatsapp import MockWhatsAppClient
from apps.notifications.catalog import DEFAULT_TEXTS, default_text, texts_in
from apps.notifications.defaults import languages
from apps.notifications.models import Audience, Notification
from apps.notifications.render import render
from apps.orders.tests.helpers import make_shop
from apps.payments import services as payments
from apps.payments.services import PaymentInput
from apps.platform import selectors
from apps.platform.models import FeatureFlag, TenantFeature
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
VARIABLE = re.compile(r"{{\s*(\w+)\s*}}")


@pytest.fixture(autouse=True)
def _daytime(monkeypatch):
    monkeypatch.setattr(quiet, "current_hold", lambda now: None)
    MockWhatsAppClient.outbox.clear()


def test_every_default_text_is_in_every_language_with_the_same_variables():
    others = [code for code in languages() if code != "en"]
    assert others == ["hi", "mr"]
    for locale in others:
        for event, audiences in DEFAULT_TEXTS.items():
            for audience, channels in audiences.items():
                if audience == Audience.SUPPLIER:  # suppliers' letters stay English (owner)
                    assert default_text(event, audience, "EMAIL", locale) is None
                    continue
                for channel, english in channels.items():
                    text = default_text(event, audience, channel, locale)
                    assert text is not None, (locale, event, audience, channel)
                    used = set(VARIABLE.findall(text.subject + text.body))
                    expected = set(VARIABLE.findall(english.subject + english.body))
                    if channel == "SMS":  # short enough for one part: may leave some out
                        assert used <= expected, (locale, event)
                    else:
                        assert used == expected, (locale, event, audience, channel)
                    if channel in ("WHATSAPP", "SMS"):  # one platform number for everyone
                        assert text.body.startswith("{{ distributor }}: "), (locale, event)
                    if channel == "WHATSAPP":
                        assert text.variables == tuple(dict.fromkeys(VARIABLE.findall(text.body)))


def test_the_welcome_sms_fits_one_part_in_every_language(tenant_a):
    values = {
        "distributor": "Sharma Traders",
        "shop": "Ganesh Kirana",
        "link": "https://sharma.example.in/shop",
    }
    with tenant_context(tenant_a.pk):
        rendered = {code: render("retailer.welcome", "SMS", values, code) for code in languages()}
    bodies = {}
    for locale, text in rendered.items():
        assert text is not None
        bodies[locale] = text["body"]
        assert sms_length.parts(text["body"]) == 1, (locale, text["body"])
    assert not sms_length.is_unicode(bodies["en"])
    assert sms_length.is_unicode(bodies["hi"])
    assert sms_length.parts("क" * 71) == 2 and sms_length.parts("a" * 160) == 1


@pytest.fixture
def world(tenant_a, every_language, django_capture_on_commit_callbacks):
    owner = make_staff_in(tenant_a, "OWNER")  # acts; doesn't hear of its own actions
    accounts = make_staff_in(tenant_a, "ACCOUNTS")
    User.objects.filter(pk=accounts.pk).update(preferred_language="mr")
    shop = make_shop(tenant_a, "9876500191")
    with tenant_context(tenant_a.pk):
        Retailer.objects.filter(pk=shop.pk).update(whatsapp_opt_in=True, preferred_language="hi")
        TenantFeature.objects.create(flag=FeatureFlag.objects.get(code="whatsapp"), enabled=True)
    selectors.invalidate_tenant_features(tenant_a.pk)
    return {
        "t": tenant_a,
        "owner": owner,
        "accounts": accounts,
        "shop": shop,
        "run": django_capture_on_commit_callbacks,
    }


def _pay(world: dict[str, Any]) -> dict[tuple[str, str], Notification]:
    with world["run"](execute=True), tenant_context(world["t"].pk):
        payments.record_payment(
            PaymentInput(world["shop"].pk, D("500.00"), "CASH", today_ist()), by=world["owner"]
        )
    with tenant_context(world["t"].pk):
        rows = Notification.objects.filter(event_code="payment.received")
        return {
            ("shop" if row.recipient_id != world["owner"].pk else "owner", row.channel): row
            for row in rows
        }


def test_a_hindi_shop_and_marathi_staff_each_get_their_own_words(world):
    sent = _pay(world)
    shop_in_app = sent[("shop", "IN_APP")]
    assert shop_in_app.title == "भुगतान मिला: ₹500.00"
    assert shop_in_app.body.startswith("धन्यवाद: नकद से ₹500.00")  # the mode too
    # Staff hear of a bounced cheque (the shop too), each in their language, values included.
    with world["run"](execute=True), tenant_context(world["t"].pk):
        cheque = payments.record_payment(
            PaymentInput(world["shop"].pk, D("200.00"), "CHEQUE", today_ist(), cheque_number="1"),
            by=world["owner"],
        )
    with world["run"](execute=True), tenant_context(world["t"].pk):
        payments.bounce_cheque(cheque.pk, reason="No funds", by=world["owner"])
    with tenant_context(world["t"].pk):  # messages are made once the bounce commits
        bounced = {
            row.recipient_id: row
            for row in Notification.objects.filter(event_code="payment.bounced", channel="IN_APP")
        }
    marathi = bounced[world["accounts"].pk]
    assert "बाउन्स झाला" in marathi.body and marathi.title.endswith("बाउन्स झाला")
    assert "शिल्लक ₹500.00 क्रेडिटमध्ये" in marathi.body  # the balance, in words (the cash)
    shop_row = next(
        row for pk, row in bounced.items() if pk not in (world["accounts"].pk, world["owner"].pk)
    )
    assert "बाउंस हो गया" in shop_row.body  # Hindi, the shop's words
    whatsapp = sent[("shop", "WHATSAPP")].data["whatsapp"]
    assert (whatsapp["template"], whatsapp["language"]) == ("b2b_payment_received", "hi")
    assert whatsapp["parameters"][1] == "₹500.00"


def test_an_english_edit_doesnt_replace_the_standard_hindi(world):
    with tenant_context(world["t"].pk):
        texts.save_tenant_text(
            texts.TextInput(
                "payment.received", "IN_APP", "en", "Got {{ amount }}", "Thanks, {{ amount }}."
            )
        )
        hindi = texts.texts_for("payment.received", "hi")
    shop_text = next(t for t in hindi if t["audience"] == "SHOP" and t["channel"] == "IN_APP")
    assert (shop_text["source"], shop_text["locale"]) == ("platform", "hi")
    assert shop_text["edited_locales"] == ["en"]  # the editor warns: only English changed
    assert _pay(world)[("shop", "IN_APP")].title == "भुगतान मिला: ₹500.00"

    with tenant_context(world["t"].pk):
        texts.save_tenant_text(
            texts.TextInput("payment.received", "IN_APP", "hi", "{{ amount }} मिले", "शुक्रिया।")
        )
        Notification.objects.filter(event_code="payment.received").delete()
        edited = texts.texts_for("payment.received", "hi")
    assert next(t for t in edited if t["audience"] == "SHOP" and t["channel"] == "IN_APP")[
        "edited_locales"
    ] == ["en", "hi"]
    assert _pay(world)[("shop", "IN_APP")].title == "₹500.00 मिले"


def test_a_language_without_its_own_text_falls_back_to_english(world):
    assert "kn" not in languages()
    with tenant_context(world["t"].pk):
        english = render("payment.received", "IN_APP", {"amount": "₹1.00", "mode": "UPI"}, "kn")
    assert english is not None and english["title"] == "Payment received: ₹1.00"


def test_previews_use_the_texts_language():
    data = texts.TextInput(
        "order.dispatched", "IN_APP", "hi", "{{ order_number }}", "{{ vehicle }}"
    )
    assert texts.preview(data, "Sharma")["body"] == " (गाड़ी MH12AB1234)"
    with translation.override("en"):
        english = texts.preview(
            texts.TextInput(
                "order.dispatched", "IN_APP", "en", "{{ order_number }}", "{{ vehicle }}"
            ),
            "Sharma",
        )
    assert english["body"] == " by vehicle MH12AB1234"


def test_the_catalogue_reads_each_language_once():
    assert texts_in("hi") is texts_in("hi")
    assert texts_in("en") is DEFAULT_TEXTS
