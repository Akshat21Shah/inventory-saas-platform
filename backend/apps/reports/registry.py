"""The report framework (ADR-050).

Each report is a ``Report`` definition registered here: who may open it, its filters and columns
(some marked *cost*), how its rows and totals are queried. The engine does the rest the same way
for every report: the permission, rows limited to the user's own shops where the sales-visibility
rule applies, cost columns left out without ``costs.view``, paging, totals and exports.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from common.dates import today_ist
from common.permissions import Requirement


class Kind(StrEnum):
    TEXT = "text"
    MONEY = "money"
    QTY = "qty"
    INT = "int"
    DATE = "date"
    PERCENT = "percent"


class FilterKind(StrEnum):
    DATE = "date"
    CHOICE = "choice"
    ID = "id"  # a shop, product, category, brand, salesperson…
    TEXT = "text"
    BOOL = "bool"


class Group(StrEnum):
    SALES = "sales"
    STOCK = "stock"
    MONEY = "money"
    GST = "gst"


GROUP_CHOICES = tuple((g.value, g.value) for g in Group)  # the API's ReportGroupEnum


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: Kind = Kind.TEXT
    cost: bool = False  # needs costs.view: left out of rows, totals and exports otherwise
    total: bool = False  # has a figure in the totals row
    width: int = 14  # Excel column width


@dataclass(frozen=True)
class Filter:
    key: str
    label: str
    kind: FilterKind
    required: bool = False
    choices: tuple[str, ...] = ()
    default: Callable[[], Any] | None = None
    entity: str = ""  # ID filters: shop, product, category, brand or staff (named in exports)


@dataclass(frozen=True)
class Scope:
    user_id: UUID
    own_shops: bool  # only shops whose salesperson is the user
    costs: bool  # cost columns and figures allowed


@dataclass(frozen=True)
class Context:
    params: dict[str, Any]
    scope: Scope
    # Figures worked out once per request and shared by rows and totals.
    memo: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def once(self, key: str, make: Callable[[], Any]) -> Any:
        if key not in self.memo:
            self.memo[key] = make()
        return self.memo[key]

    def shops(self, rows: Any, path: str = "retailer") -> Any:
        """Rows limited to the user's own shops when the sales-visibility rule applies. ``path``
        is the lookup to the shop from the rows' model (e.g. ``invoice__retailer``)."""
        if not self.scope.own_shops:
            return rows
        key = f"{path}__salesperson_id" if path else "salesperson_id"
        return rows.filter(**{key: self.scope.user_id})


@dataclass(frozen=True)
class Sheet:
    """One sheet of a multi-sheet export (the GST workbook)."""

    title: str
    columns: tuple[Column, ...]
    rows: Iterable[dict[str, Any]]
    preamble: tuple[tuple[Any, ...], ...] = ()  # rows above the header (the GSTR-1 template's)


@dataclass(frozen=True)
class Report:
    code: str
    title: str
    group: Group
    permission: Requirement  # to open it at all
    columns: tuple[Column, ...]
    rows: Callable[[Context], Any]  # a values() QuerySet or a list of dicts, sorted
    # The permission that shows every shop; without it, own shops only when the sales-visibility
    # rule applies (ADR-050 item 2). Empty: the report isn't about shops.
    full: str = ""
    filters: tuple[Filter, ...] = ()
    totals: Callable[[Context], dict[str, Any]] | None = None
    notes: Callable[[Context], list[str]] | None = None  # e.g. "costs marked estimated"
    description: str = ""
    pdf: bool = False
    background_only: bool = False  # always exported in the background (the GST workbook)
    max_days: int = 366  # the longest date range a filter pair may span
    sheets: Callable[[Context], list[Sheet]] | None = None  # multi-sheet export
    # Extra checks on the filters, e.g. "a whole month or quarter": field -> messages.
    check: Callable[[dict[str, Any]], dict[str, list[str]]] | None = None


REGISTRY: dict[str, Report] = {}


def register(report: Report) -> Report:
    if report.code in REGISTRY:
        raise ValueError(f"Report {report.code} is registered twice")
    REGISTRY[report.code] = report
    return report


# --- Common filters ---------------------------------------------------------------------------


def month_start() -> date:
    return today_ist().replace(day=1)


DATE_FROM = Filter("date_from", "From", FilterKind.DATE, required=True, default=month_start)
DATE_TO = Filter("date_to", "To", FilterKind.DATE, required=True, default=today_ist)
PERIOD = (DATE_FROM, DATE_TO)


def days_between(params: dict[str, Any]) -> int:
    start, end = params.get("date_from"), params.get("date_to")
    if not isinstance(start, date) or not isinstance(end, date):
        return 0
    return (end - start).days + 1


def previous_period(start: date, end: date) -> tuple[date, date]:
    """The same number of days just before (for comparisons)."""
    days = (end - start).days + 1
    return start - timedelta(days=days), start - timedelta(days=1)


class Mapped:
    """A values() queryset whose rows are completed in Python (e.g. a category path or a label),
    paged and exported like the queryset itself."""

    def __init__(self, rows: Any, complete: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.rows = rows
        self.complete = complete

    def count(self) -> int:
        return int(self.rows.count())

    def __getitem__(self, part: slice) -> list[dict[str, Any]]:
        return [self.complete(r) for r in self.rows[part]]

    def iterator(self, chunk_size: int = 2000) -> Iterable[dict[str, Any]]:
        return (self.complete(r) for r in self.rows.iterator(chunk_size=chunk_size))
