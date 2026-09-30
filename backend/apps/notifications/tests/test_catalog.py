"""The notification catalogue (ADR-048, PLAN §10.2h): the default rules, texts and urgency are
consistent with each other and with what the product owner approved."""

import re

import pytest

from apps.accounts.permissions import ALL_PERMISSIONS
from apps.notifications.catalog import (
    DEFAULT_RULES,
    DEFAULT_TEXTS,
    EVENTS,
    RECIPIENT_CHANNELS,
    in_first_submission,
    whatsapp_template_name,
)
from apps.notifications.models import Audience, PlatformTemplate

VAR = re.compile(r"{{\s*(\w+)\s*}}")


def _audience(recipient: str) -> str:
    return Audience.SHOP if recipient == "SHOP" else Audience.STAFF


def test_every_rule_names_a_real_event_recipient_channel_and_permission():
    keys = [rule.key for rule in DEFAULT_RULES]
    assert len(keys) == len(set(keys))
    for rule in DEFAULT_RULES:
        assert rule.event in EVENTS, rule
        assert set(rule.channels) <= set(RECIPIENT_CHANNELS[rule.recipient]), rule
        if rule.recipient == "STAFF_PERMISSION":
            assert rule.permission in ALL_PERMISSIONS, rule
        else:
            assert rule.permission == "", rule
        assert _audience(rule.recipient) in EVENTS[rule.event].audiences, rule
        for channel in rule.channels:  # a text in the recipient's words
            assert channel in DEFAULT_TEXTS[rule.event][_audience(rule.recipient)], rule


def test_every_event_has_texts_in_the_words_of_everyone_it_can_reach():
    for code, event in EVENTS.items():
        assert set(DEFAULT_TEXTS[code]) == set(event.audiences), code
        for audience in event.audiences:
            assert {"IN_APP", "EMAIL", "WHATSAPP"} <= set(DEFAULT_TEXTS[code][audience]), (
                code,
                audience,
            )
    assert set(DEFAULT_TEXTS["retailer.welcome"]) == {Audience.SHOP}
    assert "SMS" in DEFAULT_TEXTS["retailer.welcome"][Audience.SHOP]
    both = [code for code, event in EVENTS.items() if len(event.audiences) == 2]
    assert {"order.placed", "order.cancelled", "order.modified", "backorder.cancelled"} <= set(both)


def test_the_shop_reads_its_own_words_and_staff_the_offices():
    shop, staff = Audience.SHOP, Audience.STAFF
    assert DEFAULT_TEXTS["order.placed"][shop]["IN_APP"].body.startswith("Your order")
    assert DEFAULT_TEXTS["order.placed"][staff]["IN_APP"].body.startswith("{{ shop }} placed")
    assert DEFAULT_TEXTS["order.cancelled"][shop]["IN_APP"].body.startswith("Your order")
    assert DEFAULT_TEXTS["order.cancelled"][staff]["IN_APP"].body.startswith("{{ shop }}'s")
    for code, audiences in DEFAULT_TEXTS.items():
        for channel, text in audiences.get(staff, {}).items():
            assert "your order" not in text.body.lower(), (code, channel)  # never the shop's words
        for channel, text in audiences.get(shop, {}).items():
            assert "{{ shop }} placed" not in text.body, (code, channel)


def test_every_text_uses_only_the_events_variables():
    for code, audiences in DEFAULT_TEXTS.items():
        allowed = set(EVENTS[code].variables)
        for audience, texts in audiences.items():
            assert "IN_APP" in texts, (code, audience)
            for channel, text in texts.items():
                used = set(VAR.findall(text.subject)) | set(VAR.findall(text.body))
                assert used <= allowed, (code, audience, channel, used - allowed)
                if audience == Audience.STAFF:  # document links only go to shops
                    assert "document_link" not in used, (code, channel)


def test_whatsapp_and_sms_name_the_distributor_first_and_list_parameters_in_order():
    for code, audiences in DEFAULT_TEXTS.items():
        for audience, texts in audiences.items():
            for channel in ("WHATSAPP", "SMS"):
                if channel not in texts:
                    continue
                body = texts[channel].body
                assert body.startswith("{{ distributor }}:"), (code, audience, channel)
                if channel == "WHATSAPP":
                    seen = list(dict.fromkeys(VAR.findall(body)))
                    assert list(texts[channel].variables) == seen, (code, audience)
        assert whatsapp_template_name(code).startswith("b2b_")
    assert whatsapp_template_name("order.placed", Audience.STAFF) == "b2b_order_placed_staff"


def test_the_approved_compulsory_and_non_urgent_events():
    compulsory = {rule.event for rule in DEFAULT_RULES if rule.compulsory}
    assert compulsory == {
        "invoice.issued",
        "credit_note.issued",
        "payment.bounced",
        "payment.reminder",
        "retailer.welcome",  # not switchable (ADR-048 item 15)
    }
    assert {code for code, event in EVENTS.items() if not event.urgent} == {
        "stock.alert_opened",
        "payment.reminder",
        "handover.reminder",
        "tax.rate_change_upcoming",
        "announcement.published",
    }
    assert {code for code, event in EVENTS.items() if event.category == "MARKETING"} == {
        "announcement.published"
    }
    shop_email = {
        rule.event
        for rule in DEFAULT_RULES
        if rule.recipient == "SHOP" and "EMAIL" in rule.channels
    }
    assert shop_email == {
        "invoice.issued",
        "credit_note.issued",
        "payment.received",
        "invoice.cancelled",  # Phase 7 backend checkpoint, change 3
    }


@pytest.mark.django_db
def test_platform_templates_are_seeded_once():
    from apps.notifications.defaults import sync_platform_templates

    expected = sum(
        len(texts) for audiences in DEFAULT_TEXTS.values() for texts in audiences.values()
    )
    assert PlatformTemplate.objects.count() == expected
    whatsapp = PlatformTemplate.objects.get(
        event_code="invoice.issued", audience="SHOP", channel="WHATSAPP"
    )
    assert (whatsapp.whatsapp_template_name, whatsapp.whatsapp_category) == (
        "b2b_invoice_issued",
        "UTILITY",
    )
    office = PlatformTemplate.objects.get(
        event_code="invoice.issued", audience="STAFF", channel="WHATSAPP"
    )
    assert office.whatsapp_template_name == "b2b_invoice_issued_staff"
    PlatformTemplate.objects.filter(pk=whatsapp.pk).update(body="edited by the super admin")
    assert sync_platform_templates(PlatformTemplate) == 0  # nothing new; edits kept
    whatsapp.refresh_from_db()
    assert whatsapp.body == "edited by the super admin"


def test_staff_rely_on_in_app_and_email_and_whatsapp_goes_in_one_first_batch():
    staff_whatsapp = [
        (rule.event, rule.recipient)
        for rule in DEFAULT_RULES
        if rule.recipient != "SHOP" and "WHATSAPP" in rule.channels
    ]
    assert staff_whatsapp == [("handover.reminder", "COLLECTOR")]
    first = [
        whatsapp_template_name(code, audience)
        for code, audiences in DEFAULT_TEXTS.items()
        for audience, texts in audiences.items()
        if "WHATSAPP" in texts and in_first_submission(code, audience)
    ]
    shop = [name for name in first if not name.endswith("_staff")]
    assert len(shop) == 26 and len(first) == 27
    assert "b2b_handover_reminder_staff" in first
    for rule in DEFAULT_RULES:  # every WhatsApp the defaults send is in the first batch
        if "WHATSAPP" in rule.channels:
            assert in_first_submission(rule.event, _audience(rule.recipient)), rule
