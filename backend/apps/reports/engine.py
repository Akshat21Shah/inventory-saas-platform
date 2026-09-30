"""Running a report the same way for every definition (ADR-050): permission, scope, filters,
a page of rows with totals, and the values as the API and exports show them."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import User
from apps.platform.selectors import get_setting
from apps.reports.registry import (
    REGISTRY,
    Column,
    Context,
    FilterKind,
    Kind,
    Report,
    Scope,
    days_between,
)
from common.errors import InvalidFields, NotFound
from common.permissions import user_has_permission
from common.tenancy import require_tenant_id

COSTS = "costs.view"
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


def may_open(user: User, report: Report) -> bool:
    return user_has_permission(user, report.permission)


def available(user: User) -> list[Report]:
    return [r for r in REGISTRY.values() if may_open(user, r)]


def get(code: str, user: User) -> Report:
    """The report, if it exists and the user may open it (else not found / refused)."""
    report = REGISTRY.get(code)
    if report is None:
        raise NotFound()
    if not may_open(user, report):
        raise PermissionDenied()
    return report


def scope_for(user: User, report: Report) -> Scope:
    """Own shops only: the report is about shops, the user lacks its "every shop" permission and
    the distributor shows sales staff only their own shops (``orders.sales_visibility``)."""
    own = bool(report.full) and not user.has_permission_code(report.full)
    if own:
        own = get_setting("orders.sales_visibility", require_tenant_id()) == "ASSIGNED_RETAILERS"
    return Scope(user.pk, own_shops=own, costs=user.has_permission_code(COSTS))


def columns(report: Report, scope: Scope) -> tuple[Column, ...]:
    return tuple(c for c in report.columns if scope.costs or not c.cost)


# --- Filters ------------------------------------------------------------------------------------


def _parse_one(kind: FilterKind, raw: Any, choices: tuple[str, ...]) -> Any:
    text = str(raw).strip()
    if kind == FilterKind.DATE:
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("Use YYYY-MM-DD.") from exc
    if kind == FilterKind.ID:
        try:
            return UUID(text)
        except ValueError as exc:
            raise ValueError("Not a valid id.") from exc
    if kind == FilterKind.BOOL:
        if text.lower() in ("true", "1"):
            return True
        if text.lower() in ("false", "0"):
            return False
        raise ValueError("Use true or false.")
    if kind == FilterKind.CHOICE:
        if text not in choices:
            raise ValueError(f"Choose one of: {', '.join(choices)}.")
        return text
    return text[:100]


def parse(report: Report, given: Mapping[str, Any]) -> dict[str, Any]:
    """The report's filters from the query (defaults filled in), validated; unknown keys are
    ignored. Date ranges are bounded by the report's ``max_days``."""
    params: dict[str, Any] = {}
    errors: dict[str, list[str]] = {}
    for f in report.filters:
        raw = given.get(f.key)
        if raw in (None, ""):
            if f.default is not None:
                params[f.key] = f.default()
            elif f.required:
                errors[f.key] = ["This field is required."]
            continue
        try:
            params[f.key] = _parse_one(f.kind, raw, f.choices)
        except ValueError as exc:
            errors[f.key] = [str(exc)]
    if not errors and "date_from" in params and "date_to" in params:
        if params["date_from"] > params["date_to"]:
            errors["date_to"] = ["The end date is before the start date."]
        elif days_between(params) > report.max_days:
            errors["date_to"] = [f"Choose at most {report.max_days} days."]
    if errors:
        raise InvalidFields(errors)
    return params


# --- Values -------------------------------------------------------------------------------------


def shown(kind: Kind, value: Any) -> Any:
    """A value as the API gives it: money to the paisa and quantities to 3 places as strings,
    dates as ISO strings."""
    if value is None:
        return None
    if kind == Kind.MONEY:
        return f"{Decimal(value):.2f}"
    if kind == Kind.QTY:
        return f"{Decimal(value):.3f}"
    if kind == Kind.PERCENT:
        return f"{Decimal(value):.1f}"
    if kind == Kind.INT:
        return int(value)
    if kind == Kind.DATE:
        return value.isoformat() if isinstance(value, date | datetime) else str(value)
    if isinstance(value, UUID):
        return str(value)
    return value


def row_out(
    row: Mapping[str, Any], cols: Iterable[Column], extra: Iterable[str] = ()
) -> dict[str, Any]:
    """Only the columns the user may see (plus link ids such as ``retailer_id``)."""
    out = {c.key: shown(c.kind, row.get(c.key)) for c in cols}
    for key in extra:
        if key in row:
            out[key] = shown(Kind.TEXT, row[key])
    return out


@dataclass(frozen=True)
class Page:
    columns: tuple[Column, ...]
    rows: list[dict[str, Any]]
    totals: dict[str, Any] | None
    count: int
    page: int
    page_size: int
    own_shops: bool
    notes: list[str]


LINKS = ("retailer_id", "product_id", "invoice_id", "order_id", "payment_id", "user_id")


def count(rows: Any) -> int:
    return rows.count() if isinstance(rows, QuerySet) else len(rows)


def page(report: Report, ctx: Context, number: int = 1, size: int = DEFAULT_PAGE_SIZE) -> Page:
    size = max(1, min(size, MAX_PAGE_SIZE))
    number = max(1, number)
    rows = report.rows(ctx)
    total = count(rows)
    start = (number - 1) * size
    chunk = list(rows[start : start + size])
    cols = columns(report, ctx.scope)
    totals = None
    if report.totals is not None:
        raw = report.totals(ctx)
        totals = {c.key: shown(c.kind, raw.get(c.key)) for c in cols if c.total}
    return Page(
        columns=cols,
        rows=[row_out(r, cols, LINKS) for r in chunk],
        totals=totals,
        count=total,
        page=number,
        page_size=size,
        own_shops=ctx.scope.own_shops,
        notes=report.notes(ctx) if report.notes else [],
    )
