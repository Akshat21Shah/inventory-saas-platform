"""The assistant's tools (ADR-059 item 1): a fixed list, each a report run through the report
engine with the asking person's permissions, so a tool shows exactly what that person's Reports
page shows (sales staff their own shops, costs only with ``costs.view``, optional modules
respected). Read-only; the model never writes a query.

A tool's result is the report's first rows (at most 20) with its columns and, for whole reports,
its totals; the same figures are kept with the question and shown under the answer."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import User
from apps.ai.adapters.chat import ToolSpec
from apps.ai.assistant import periods
from apps.reports import engine
from apps.reports.registry import REGISTRY, Context, Mapped, Report
from common.errors import InvalidFields, NotFound

MAX_ROWS = 20

PERIOD = {
    "type": "string",
    "enum": list(periods.PERIODS),
    "description": "The period in India time (weeks start on Monday, the financial year on "
    "1 April). Default: this_month.",
}
LIMIT = {
    "type": "integer",
    "minimum": 1,
    "maximum": MAX_ROWS,
    "description": "How many rows at most. Default: 10.",
}
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_PHONE = re.compile(r"(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}")
_KEEP = {"code", "number"}  # product and document codes are never personal details


class ToolError(Exception):
    """The arguments or the person's access don't allow this call (told to the model)."""


@dataclass(frozen=True)
class Tool:
    name: str
    report: str
    description: str
    properties: dict[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    period: bool = False
    limit: int = 10
    totals: bool = True  # the report's totals row (whole reports only)
    hidden: frozenset[str] = frozenset()  # columns never sent (references, handovers)
    filters: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    select: Callable[[Any, dict[str, Any]], Any] | None = None  # narrow or re-sort the rows

    def spec(self) -> ToolSpec:
        properties = dict(self.properties)
        if self.period:
            properties = {"period": PERIOD, **properties}
        properties.setdefault("limit", LIMIT)
        schema = {"type": "object", "properties": properties, "required": list(self.required)}
        return ToolSpec(self.name, self.description, schema)


# --- Narrowing and sorting ------------------------------------------------------------------


def _not_ordering(rows: list[dict[str, Any]], args: dict[str, Any]) -> list[dict[str, Any]]:
    days = args["days"]
    found = [r for r in rows if r["days_since"] is None or r["days_since"] >= days]
    # The longest gaps first; shops that never ordered after them.
    return sorted(
        found, key=lambda r: (r["days_since"] is None, -(r["days_since"] or 0), r["name"])
    )


def _matching_products(rows: Mapped, args: dict[str, Any]) -> Mapped:
    from apps.catalog.models import Product
    from apps.catalog.search import ranked_queryset

    live = Product.objects.filter(deleted_at__isnull=True)
    ids = list(ranked_queryset(live, args["product"]).values_list("pk", flat=True)[:MAX_ROWS])
    return Mapped(rows.rows.filter(id__in=ids), rows.complete)


def _most_short(rows: Mapped, args: dict[str, Any]) -> Mapped:
    return Mapped(rows.rows.order_by("-shortfall", "name", "id"), rows.complete)


def _most_owed(rows: list[dict[str, Any]], args: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (-(r["net"] or 0), r["name"]))


def _group_by(args: dict[str, Any]) -> dict[str, Any]:
    start, end = args["date_from"], args["date_to"]
    days = (end - start).days + 1
    return {
        "group_by": args.get("group_by")
        or ("day" if days <= 14 else "week" if days <= 62 else "month")
    }


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            "sales_summary",
            "sales_summary",
            "Sales totals for a period, split by day, week or month: invoices, billed, credited "
            "(returns), taxable value, tax and the net total. Use for 'how much did we sell'.",
            {"group_by": {"type": "string", "enum": ["day", "week", "month"]}},
            period=True,
            limit=MAX_ROWS,
            filters=_group_by,
        ),
        Tool(
            "top_products",
            "sales_by_product",
            "Products by sales value in a period, highest first: quantity sold, free quantity, "
            "taxable value, tax, total and share of sales.",
            period=True,
        ),
        Tool(
            "sales_by_category",
            "sales_by_category",
            "Sales by product category in a period, highest first, with each category's share.",
            period=True,
        ),
        Tool(
            "top_shops",
            "sales_by_shop",
            "Shops by sales value in a period, highest first: invoices, total, share and their "
            "last invoice date.",
            period=True,
        ),
        Tool(
            "sales_by_salesperson",
            "sales_by_salesperson",
            "Sales by salesperson in a period: shops, invoices, total and share.",
            period=True,
        ),
        Tool(
            "shops_not_ordering",
            "shop_activity",
            "Shops that haven't ordered for at least `days` days, the longest gap first, then "
            "shops that never ordered: last order, days since, usual gap and recent order values.",
            {
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 365,
                    "description": "Default 30.",
                }
            },
            totals=False,
            select=_not_ordering,
        ),
        Tool(
            "low_stock",
            "low_stock",
            "Products at or below their reorder level, the biggest shortfall first: available, "
            "reorder level and shortfall.",
            totals=False,
            select=_most_short,
        ),
        Tool(
            "product_stock",
            "stock_summary",
            "Stock of the products matching a name or code: on hand, held for orders, available, "
            "reorder level and status.",
            {"product": {"type": "string", "description": "A product name or code, as typed."}},
            required=("product",),
            totals=False,
            select=_matching_products,
        ),
        Tool(
            "dues",
            "receivables_ageing",
            "What shops owe, the most first: amounts by age (not due, 0-30, 31-60, 61-90, 90+ "
            "days), credit held, net owed, credit limit, oldest due date and last payment.",
            {"overdue_only": {"type": "boolean", "description": "Only shops with overdue dues."}},
            select=_most_owed,
        ),
        Tool(
            "collections",
            "collections",
            "Payments received in a period, newest first, with the total collected.",
            {
                "mode": {
                    "type": "string",
                    "enum": ["CASH", "CHEQUE", "BANK_TRANSFER", "UPI", "ONLINE"],
                    "description": "Only payments made this way.",
                }
            },
            period=True,
            hidden=frozenset({"reference", "handover"}),
            filters=lambda args: {"mode": args["mode"]} if args.get("mode") else {},
        ),
        Tool(
            "backorders",
            "backorder_demand",
            "Products shops are waiting for (backorders): shops waiting, quantity, oldest, "
            "available now, quantity on order and when it is expected.",
            totals=False,
        ),
    )
}


# --- Access ---------------------------------------------------------------------------------


def usable(user: User, tool: Tool) -> bool:
    report = REGISTRY.get(tool.report)
    return report is not None and engine.may_open(user, report)


def tools_for(user: User) -> list[Tool]:
    """The tools this person may use (their reports), in a fixed order."""
    return [t for t in TOOLS.values() if usable(user, t)]


# --- Arguments ------------------------------------------------------------------------------


def _int(value: Any, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ToolError(f"{name} must be a whole number from {low} to {high}.")
    try:
        number = int(value)
    except ValueError as exc:
        raise ToolError(f"{name} must be a whole number from {low} to {high}.") from exc
    if not low <= number <= high:
        raise ToolError(f"{name} must be from {low} to {high}.")
    return number


def clean(tool: Tool, args: dict[str, Any]) -> dict[str, Any]:
    """The arguments checked and completed with their defaults (``ToolError`` otherwise)."""
    if not isinstance(args, dict):
        raise ToolError("Arguments must be an object.")
    unknown = set(args) - set(tool.spec().schema["properties"])
    if unknown:
        raise ToolError(f"Unknown arguments: {', '.join(sorted(unknown))}.")
    out: dict[str, Any] = {"limit": _int(args.get("limit", tool.limit), "limit", 1, MAX_ROWS)}
    if tool.period:
        period = str(args.get("period") or "this_month")
        try:
            out["date_from"], out["date_to"] = periods.dates(period)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        out["period"] = period
        if args.get("group_by") not in (None, "day", "week", "month"):
            raise ToolError("group_by must be day, week or month.")
        if args.get("group_by"):
            out["group_by"] = args["group_by"]
    if "days" in tool.properties:
        out["days"] = _int(args.get("days", 30), "days", 1, 365)
    if "product" in tool.properties:
        text = " ".join(str(args.get("product") or "").split())[:60]
        if len(text) < 2:
            raise ToolError("product must name a product (2 characters or more).")
        out["product"] = text
    if "overdue_only" in tool.properties:
        out["overdue_only"] = bool(args.get("overdue_only", False))
    if "mode" in tool.properties and args.get("mode"):
        if args["mode"] not in tool.properties["mode"]["enum"]:
            raise ToolError("Unknown payment mode.")
        out["mode"] = args["mode"]
    return out


# --- Running --------------------------------------------------------------------------------


def _scrub(key: str, value: Any) -> Any:
    """Never send an email address or a phone number (ADR-059 item 5)."""
    if not isinstance(value, str) or key in _KEEP:
        return value
    return _PHONE.sub("—", _EMAIL.sub("—", value))


@dataclass(frozen=True)
class Figures:
    """What a tool returned, kept with the question and shown under the answer."""

    tool: str
    report: str
    title: str
    date_from: date | None
    date_to: date | None
    columns: list[dict[str, str]]
    rows: list[dict[str, Any]]
    totals: dict[str, Any] | None
    count: int
    own_shops: bool
    notes: list[str]

    def as_json(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "report": self.report,
            "title": self.title,
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "columns": self.columns,
            "rows": self.rows,
            "totals": self.totals,
            "count": self.count,
            "own_shops": self.own_shops,
            "notes": self.notes,
        }

    def for_model(self) -> dict[str, Any]:
        """What the model reads: the figures without the app's link ids."""
        return {
            "report": self.title,
            "period": {"from": self.date_from.isoformat(), "to": self.date_to.isoformat()}
            if self.date_from and self.date_to
            else None,
            "columns": {c["key"]: c["label"] for c in self.columns},
            "rows": [{c["key"]: r.get(c["key"]) for c in self.columns} for r in self.rows],
            "rows_found": self.count,
            "rows_shown": len(self.rows),
            "totals": self.totals,
            "only_the_askers_own_shops": self.own_shops,
            "notes": self.notes,
        }


def _report(user: User, tool: Tool) -> Report:
    try:
        return engine.get(tool.report, user)
    except (PermissionDenied, NotFound) as exc:
        raise ToolError("This isn't available to you.") from exc


def run(user: User, name: str, args: dict[str, Any]) -> Figures:
    """Run a tool for ``user`` in the active distributor (``ToolError`` when it can't)."""
    tool = TOOLS.get(name)
    if tool is None or not usable(user, tool):
        raise ToolError("This isn't available to you.")
    given = clean(tool, args)
    report = _report(user, tool)
    filters: dict[str, Any] = {}
    if tool.period:
        filters = {
            "date_from": given["date_from"].isoformat(),
            "date_to": given["date_to"].isoformat(),
        }
    if tool.filters is not None:
        filters.update(tool.filters(given))
    if given.get("overdue_only"):
        filters["overdue_only"] = "true"
    try:
        ctx = Context(engine.parse(report, filters), engine.scope_for(user, report))
    except InvalidFields as exc:
        raise ToolError(f"Those filters don't work: {exc.details.get('fields', {})}") from exc
    columns = [c for c in engine.columns(report, ctx.scope) if c.key not in tool.hidden]
    rows: Any = report.rows(ctx)
    if tool.select is not None:
        rows = tool.select(rows, given)
    count = engine.count(rows)
    shown = [
        {k: _scrub(k, v) for k, v in engine.row_out(r, columns, engine.LINKS).items()}
        for r in list(rows[: given["limit"]])
    ]
    totals = None
    if tool.totals and report.totals is not None:
        raw = report.totals(ctx)
        totals = {c.key: engine.shown(c.kind, raw.get(c.key)) for c in columns if c.total}
    return Figures(
        tool=tool.name,
        report=report.code,
        title=str(report.title),
        date_from=given.get("date_from"),
        date_to=given.get("date_to"),
        columns=[{"key": c.key, "label": c.label, "kind": c.kind.value} for c in columns],
        rows=shown,
        totals=totals or None,
        count=count,
        own_shops=ctx.scope.own_shops,
        notes=report.notes(ctx) if report.notes else [],
    )
