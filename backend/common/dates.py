"""Business dates are Indian calendar dates (IST), whatever the server's timezone (CLAUDE.md §5:
store UTC, reason about days in Asia/Kolkata)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

IST = ZoneInfo("Asia/Kolkata")


def today_ist() -> date:
    return timezone.now().astimezone(IST).date()


def to_ist(moment: datetime) -> datetime:
    return moment.astimezone(IST)
