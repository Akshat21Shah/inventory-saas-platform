"""Named periods the assistant's tools take (ADR-059 item 1), as dates in India time."""

from __future__ import annotations

from datetime import date, timedelta

from common.dates import today_ist

PERIODS = (
    "today",
    "yesterday",
    "this_week",
    "last_week",
    "last_7_days",
    "this_month",
    "last_month",
    "last_30_days",
    "last_90_days",
    "this_quarter",
    "last_quarter",
    "this_financial_year",
    "last_financial_year",
)
WORDS = {
    "today": "today",
    "yesterday": "yesterday",
    "this_week": "this week",
    "last_week": "last week",
    "last_7_days": "in the last 7 days",
    "this_month": "this month",
    "last_month": "last month",
    "last_30_days": "in the last 30 days",
    "last_90_days": "in the last 90 days",
    "this_quarter": "this quarter",
    "last_quarter": "last quarter",
    "this_financial_year": "this financial year",
    "last_financial_year": "last financial year",
}


def _quarter_start(day: date) -> date:
    return day.replace(month=(day.month - 1) // 3 * 3 + 1, day=1)


def _fy_start(day: date) -> date:
    return date(day.year if day.month >= 4 else day.year - 1, 4, 1)


def dates(period: str, today: date | None = None) -> tuple[date, date]:
    """The first and last day of ``period`` (a week starts on Monday; the financial year on
    1 April). Raises ``ValueError`` for an unknown period."""
    day = today or today_ist()
    if period == "today":
        return day, day
    if period == "yesterday":
        return day - timedelta(days=1), day - timedelta(days=1)
    if period == "this_week":
        return day - timedelta(days=day.weekday()), day
    if period == "last_week":
        end = day - timedelta(days=day.weekday() + 1)
        return end - timedelta(days=6), end
    if period in ("last_7_days", "last_30_days", "last_90_days"):
        days = int(period.split("_")[1])
        return day - timedelta(days=days - 1), day
    if period == "this_month":
        return day.replace(day=1), day
    if period == "last_month":
        end = day.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if period == "this_quarter":
        return _quarter_start(day), day
    if period == "last_quarter":
        end = _quarter_start(day) - timedelta(days=1)
        return _quarter_start(end), end
    if period == "this_financial_year":
        return _fy_start(day), day
    if period == "last_financial_year":
        end = _fy_start(day) - timedelta(days=1)
        return _fy_start(end), end
    raise ValueError(f"Unknown period {period!r}; use one of: {', '.join(PERIODS)}.")
