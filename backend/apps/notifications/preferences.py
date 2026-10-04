"""Which messages a person gets on which channel (ADR-048 item 7). Everything a rule sends is on
by default; a person can switch a channel off, except in-app (never) and, for a shop, the
channels of compulsory events (bills, credit notes, bounced cheques, payment reminders,
welcome). WhatsApp additionally needs the shop's consent (``consent``). The app notification is
listed only for a shop login with the app on a phone (ADR-061 item 7)."""

from typing import Any

from django.utils.translation import gettext

from apps.accounts.models import User
from apps.notifications.catalog import EVENTS
from apps.notifications.models import Channel, DeviceToken, NotificationPreference, Recipient
from apps.notifications.rules import EffectiveRule, available, effective_rules
from apps.retailers.models import Retailer
from common.errors import InvalidFields, NotFound


def _staff_gets(user: User, rule: EffectiveRule) -> bool:
    if rule.recipient == Recipient.STAFF_PERMISSION:
        return user.has_permission_code(rule.permission)
    if rule.recipient == Recipient.OWNERS:
        return user.has_permission_code("settings.manage")  # the owner-only permission
    if rule.recipient == Recipient.SALESPERSON:
        return Retailer.objects.filter(salesperson=user, deleted_at__isnull=True).exists()
    if rule.recipient == Recipient.COLLECTOR:
        return user.has_permission_code("payments.collect")
    if rule.recipient == Recipient.DISPATCHER:
        return user.has_permission_code("orders.fulfil")
    return False


def _events_for(user: User, shop: bool) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for rule in effective_rules():
        if not rule.enabled or not rule.channels or not available(rule.event):
            continue
        mine = rule.recipient == Recipient.SHOP if shop else _staff_gets(user, rule)
        if not mine:
            continue
        entry = found.setdefault(rule.event, {"channels": set(), "compulsory": False})
        entry["channels"] |= set(rule.channels)
        entry["compulsory"] = entry["compulsory"] or (shop and rule.compulsory)
    return found


def settings_for(user: User, *, shop: bool) -> list[dict[str, Any]]:
    """The person's messages with each channel's state, grouped as the catalogue groups them."""
    off = set(
        NotificationPreference.objects.filter(user=user, enabled=False).values_list(
            "event_code", "channel"
        )
    )
    has_app = shop and DeviceToken.objects.filter(user=user, is_active=True).exists()
    rows = []
    for code, entry in _events_for(user, shop).items():
        event = EVENTS[code]
        channels = [
            {
                "channel": channel,
                "enabled": channel == Channel.IN_APP
                or entry["compulsory"]
                or (code, channel) not in off,
                "locked": channel == Channel.IN_APP or entry["compulsory"],
            }
            for channel in Channel.values
            if channel in entry["channels"] and (channel != Channel.PUSH or has_app)
        ]
        rows.append(
            {
                "event": code,
                "label": event.label,
                "group": event.group,
                "compulsory": entry["compulsory"],
                "channels": channels,
            }
        )
    order = list(EVENTS)
    return sorted(rows, key=lambda r: order.index(r["event"]))


def set_preference(
    user: User, event_code: str, channel: str, enabled: bool, *, shop: bool
) -> NotificationPreference:
    if event_code not in EVENTS:
        raise NotFound()
    entry = _events_for(user, shop).get(event_code)
    if entry is None or channel not in entry["channels"]:
        raise InvalidFields({"channel": [gettext("You don't get this message on this channel.")]})
    if not enabled and channel == Channel.IN_APP:
        raise InvalidFields({"channel": [gettext("Messages in the app can't be switched off.")]})
    if not enabled and entry["compulsory"]:
        raise InvalidFields(
            {"channel": [gettext("This message is required and can't be switched off.")]}
        )
    pref: NotificationPreference
    pref, _ = NotificationPreference.objects.update_or_create(
        user=user, event_code=event_code, channel=channel, defaults={"enabled": enabled}
    )
    return pref
