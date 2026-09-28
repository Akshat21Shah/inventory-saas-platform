"""Quiet hours (ADR-048 item 9): non-urgent WhatsApp, SMS and email wait while the distributor's
quiet hours last (⚙ ``notifications.quiet_hours_start`` / ``_end``, IST, default 21:00 to 08:00) and
go out when they end. In-app is never held; urgent events (what the shop just did or must know
now) are never held."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings

IST = ZoneInfo(settings.DISPLAY_TIME_ZONE)


def _clock(text: str) -> time:
    hours, minutes = text.split(":")
    return time(int(hours), int(minutes))


def held_until(now: datetime, start: str, end: str) -> datetime | None:
    """When a message created at ``now`` may go out, or None to send at once. The window may
    cross midnight (21:00 to 08:00) or not (13:00 to 14:00); equal times mean no quiet hours."""
    begin, finish = _clock(start), _clock(end)
    if begin == finish:
        return None
    local = now.astimezone(IST)
    clock = local.time()
    crosses_midnight = begin > finish
    inside = (clock >= begin or clock < finish) if crosses_midnight else begin <= clock < finish
    if not inside:
        return None
    release = datetime.combine(local.date(), finish, tzinfo=IST)
    if release <= local:  # after the start, before midnight: tomorrow morning
        release += timedelta(days=1)
    return release


def current_hold(now: datetime) -> datetime | None:
    """For the active tenant's settings."""
    from apps.platform.selectors import get_setting

    return held_until(
        now,
        str(get_setting("notifications.quiet_hours_start")),
        str(get_setting("notifications.quiet_hours_end")),
    )
