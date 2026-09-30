"""Business dates are Indian calendar dates (IST), whatever the server's timezone (CLAUDE.md §5:
store UTC, reason about days in Asia/Kolkata)."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

IST = ZoneInfo("Asia/Kolkata")


def today_ist() -> date:
    return timezone.now().astimezone(IST).date()


def to_ist(moment: datetime) -> datetime:
    return moment.astimezone(IST)


def ist_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """The moments from the start of ``start`` to the start of the day after ``end``, in IST:
    ``moment >= first and moment < last`` covers those Indian dates (reports, ADR-050)."""
    first = datetime.combine(start, time.min, tzinfo=IST)
    return first, datetime.combine(end + timedelta(days=1), time.min, tzinfo=IST)
