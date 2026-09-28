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
    whatsapp_template_name,
)
from apps.notifications.models import PlatformTemplate

VAR = re.compile(r"{{\s*(\w+)\s*}}")


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
        if rule.recipient == "SHOP":
            assert EVENTS[rule.event].shop_facing, rule


def test_every_channel_in_use_has_a_text_with_only_the_events_variables():
    for rule in DEFAULT_RULES:
        for channel in rule.channels:
            assert channel in DEFAULT_TEXTS[rule.event], (rule.event, channel)
    for code, texts in DEFAULT_TEXTS.items():
        allowed = set(EVENTS[code].variables)
        assert "IN_APP" in texts, code
        for channel, text in texts.items():
            used = set(VAR.findall(text.subject)) | set(VAR.findall(text.body))
            assert used <= allowed, (code, channel, used - allowed)


def test_whatsapp_and_sms_name_the_distributor_first_and_list_parameters_in_order():
    for code, texts in DEFAULT_TEXTS.items():
        for channel in ("WHATSAPP", "SMS"):
            if channel not in texts:
                continue
            body = texts[channel].body
            assert body.startswith("{{ distributor }}:"), (code, channel)
            if channel == "WHATSAPP":
                seen = list(dict.fromkeys(VAR.findall(body)))
                assert list(texts[channel].variables) == seen, code
        assert whatsapp_template_name(code).startswith("b2b_")


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
    assert shop_email == {"invoice.issued", "credit_note.issued", "payment.received"}


@pytest.mark.django_db
def test_platform_templates_are_seeded_once():
    from apps.notifications.defaults import sync_platform_templates

    expected = sum(len(texts) for texts in DEFAULT_TEXTS.values())
    assert PlatformTemplate.objects.count() == expected
    whatsapp = PlatformTemplate.objects.get(event_code="invoice.issued", channel="WHATSAPP")
    assert (whatsapp.whatsapp_template_name, whatsapp.whatsapp_category) == (
        "b2b_invoice_issued",
        "UTILITY",
    )
    PlatformTemplate.objects.filter(pk=whatsapp.pk).update(body="edited by the super admin")
    assert sync_platform_templates(PlatformTemplate) == 0  # nothing new; edits kept
    whatsapp.refresh_from_db()
    assert whatsapp.body == "edited by the super admin"
