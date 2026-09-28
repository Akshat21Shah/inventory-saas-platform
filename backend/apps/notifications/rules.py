"""The rules in force for a tenant: the catalogue's defaults, overridden by the tenant's rows
(same event, recipient and permission), plus any extra recipients the tenant added."""

from dataclasses import dataclass

from apps.notifications.catalog import DEFAULT_RULES, EVENTS
from apps.notifications.models import NotificationRule


@dataclass(frozen=True)
class EffectiveRule:
    event: str
    recipient: str
    permission: str
    channels: tuple[str, ...]
    enabled: bool
    compulsory: bool
    is_default: bool  # False: added or changed by the tenant

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.event, self.recipient, self.permission)


def effective_rules(event_code: str | None = None) -> list[EffectiveRule]:
    """For the active tenant; all events, or one."""
    merged: dict[tuple[str, str, str], EffectiveRule] = {
        rule.key: EffectiveRule(
            rule.event, rule.recipient, rule.permission, tuple(rule.channels), True,
            rule.compulsory, True,
        )
        for rule in DEFAULT_RULES
        if event_code is None or rule.event == event_code
    }  # fmt: skip
    rows = NotificationRule.objects.all()
    if event_code is not None:
        rows = rows.filter(event_code=event_code)
    for row in rows:
        if row.event_code not in EVENTS:
            continue  # an event retired from the catalogue
        rule = EffectiveRule(
            row.event_code,
            row.recipient,
            row.permission,
            tuple(row.channels),
            row.is_enabled,
            row.is_compulsory,
            False,
        )
        merged[rule.key] = rule
    return sorted(merged.values(), key=lambda r: (r.event, r.recipient, r.permission))


def is_compulsory(event_code: str) -> bool:
    """The shop can't switch off this event's channels (ADR-048 item 7)."""
    return any(
        r.compulsory and r.enabled and r.recipient == "SHOP" for r in effective_rules(event_code)
    )


# --- Changing an event's rules (``notifications.manage``) ---------------------------------------


@dataclass(frozen=True)
class RuleInput:
    recipient: str
    channels: tuple[str, ...]
    permission: str = ""
    enabled: bool = True
    compulsory: bool = False

    @property
    def key(self) -> tuple[str, str]:
        return (self.recipient, self.permission)


def _as_dict(rule: EffectiveRule) -> dict[str, object]:
    return {
        "recipient": rule.recipient,
        "permission": rule.permission,
        "channels": list(rule.channels),
        "enabled": rule.enabled,
        "compulsory": rule.compulsory,
    }


def _check(event_code: str, rules: list[RuleInput]) -> None:
    from apps.accounts.permissions import TENANT_PERMISSIONS
    from apps.notifications.catalog import DEFAULT_TEXTS, RECIPIENT_CHANNELS
    from apps.notifications.models import Recipient
    from common.errors import InvalidFields

    event = EVENTS[event_code]
    tenant_codes = {p.code for p in TENANT_PERMISSIONS}
    texts = DEFAULT_TEXTS.get(event_code, {})
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for rule in rules:
        if rule.recipient not in Recipient.values:
            errors.append(f"Unknown recipient {rule.recipient}.")
            continue
        if rule.key in seen:
            errors.append("Each recipient can appear only once.")
        seen.add(rule.key)
        if rule.recipient == Recipient.STAFF_PERMISSION and rule.permission not in tenant_codes:
            errors.append("Choose which staff (a permission) should get it.")
        if rule.recipient != Recipient.STAFF_PERMISSION and rule.permission:
            errors.append("Only 'Staff who can…' takes a permission.")
        if rule.recipient == Recipient.SHOP and not event.shop_facing:
            errors.append("This message is for staff only.")
        if rule.compulsory and rule.recipient != Recipient.SHOP:
            errors.append("Only the shop's messages can be compulsory.")
        for channel in rule.channels:
            if channel not in RECIPIENT_CHANNELS[rule.recipient]:
                errors.append(f"{channel} can't be used for this recipient.")
            elif channel not in texts:
                errors.append(f"There is no {channel} text for this message yet.")
    if errors:
        raise InvalidFields({"rules": list(dict.fromkeys(errors))})


def save_rules(event_code: str, rules: list[RuleInput]) -> list[EffectiveRule]:
    """Replace the tenant's rules for one event. Defaults left out are kept switched off; rules
    equal to a default store nothing. Audited."""
    from apps.audit import services as audit
    from common.errors import NotFound

    if event_code not in EVENTS:
        raise NotFound()
    _check(event_code, rules)
    before = [_as_dict(r) for r in effective_rules(event_code)]
    defaults = {(r.recipient, r.permission): r for r in DEFAULT_RULES if r.event == event_code}
    NotificationRule.objects.filter(event_code=event_code).delete()
    given = {rule.key for rule in rules}
    rows = []
    for rule in rules:
        default = defaults.get(rule.key)
        same = (
            default is not None
            and rule.enabled
            and set(rule.channels) == set(default.channels)
            and rule.compulsory == default.compulsory
        )
        if not same:
            rows.append(
                NotificationRule(
                    event_code=event_code,
                    recipient=rule.recipient,
                    permission=rule.permission,
                    channels=list(dict.fromkeys(rule.channels)),
                    is_enabled=rule.enabled,
                    is_compulsory=rule.compulsory,
                )
            )
    for key, default in defaults.items():
        if key not in given:
            rows.append(
                NotificationRule(
                    event_code=event_code,
                    recipient=default.recipient,
                    permission=default.permission,
                    channels=list(default.channels),
                    is_enabled=False,
                    is_compulsory=default.compulsory,
                )
            )
    for row in rows:
        row.save()
    after = effective_rules(event_code)
    audit.record(
        "notifications.rules_changed",
        target_type="NotificationEvent",
        target_id="",
        target_repr=event_code,
        changes={"rules": [before, [_as_dict(r) for r in after]]},
    )
    return after


def reset_rules(event_code: str) -> list[EffectiveRule]:
    from apps.audit import services as audit
    from common.errors import NotFound

    if event_code not in EVENTS:
        raise NotFound()
    removed, _ = NotificationRule.objects.filter(event_code=event_code).delete()
    if removed:
        audit.record(
            "notifications.rules_reset", target_type="NotificationEvent", target_repr=event_code
        )
    return effective_rules(event_code)
