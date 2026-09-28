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
