"""Sales reports (ADR-050 items 3-5).

Sales are invoices by invoice date minus credit notes by note date: taxable value, GST and total.
Invoices whose IRN was cancelled (status CANCELLED) are left out; their re-issues count. Cost is
the cost recorded on each invoice line when it was issued; lines issued before that (or of
products then without a cost) use today's cost price and are counted as "estimated"; lines with
no cost at all are left out of the margin. Returns take off their quantity at the invoice line's
cost; value-only credit notes reduce the sales, not the cost."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import (
    Case,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    IntegerField,
    Max,
    OuterRef,
    QuerySet,
    Subquery,
    Sum,
    UUIDField,
    Value,
    When,
)
from django.db.models.fields.json import KT
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek
from django.db.models.lookups import IsNull

from apps.accounts.models import User
from apps.billing.models import CreditNote, CreditNoteLine, DocumentStatus, Invoice, InvoiceLine
from apps.catalog.models import Brand, Category, Product
from apps.catalog.selectors import descendant_ids
from apps.reports.registry import (
    PERIOD,
    Column,
    Context,
    Filter,
    FilterKind,
    Group,
    Kind,
    Report,
    register,
)
from apps.retailers.models import Retailer
from common.permissions import AllOf, AnyOf

SALES = AnyOf(("reports.sales", "reports.sales_own"))
MARGIN = AllOf(("costs.view", AnyOf(("reports.sales", "reports.financial"))))
ZERO = Decimal("0")
MONEY = DecimalField(max_digits=20, decimal_places=4)
ISSUED = DocumentStatus.ISSUED

CATEGORY = Filter("category", "Category", FilterKind.ID, entity="category")
BRAND = Filter("brand", "Brand", FilterKind.ID, entity="brand")
SHOP = Filter("shop", "Shop", FilterKind.ID, entity="shop")
SALESPERSON = Filter("salesperson", "Salesperson", FilterKind.ID, entity="staff")


# --- The facts: invoice lines and credit note lines in the period -------------------------------


@dataclass(frozen=True)
class Paths:
    """How each kind of line reaches the product, the shop, the salesperson and its date."""

    product: str
    shop: str
    salesperson: str
    day: str
    unit_cost: str


INVOICE = Paths(
    "product",
    "invoice__retailer",
    "invoice__order__salesperson",
    "invoice__invoice_date",
    "unit_cost",
)
CREDIT = Paths(
    "invoice_line__product",
    "credit_note__retailer",
    "credit_note__invoice__order__salesperson",
    "credit_note__note_date",
    "invoice_line__unit_cost",
)


def _narrow(rows: QuerySet[Any], ctx: Context, paths: Paths) -> QuerySet[Any]:
    p = ctx.params
    rows = ctx.shops(rows, paths.shop).filter(
        **{f"{paths.day}__gte": p["date_from"], f"{paths.day}__lte": p["date_to"]}
    )
    if p.get("category"):
        rows = rows.filter(**{f"{paths.product}__category_id__in": descendant_ids(p["category"])})
    if p.get("brand"):
        rows = rows.filter(**{f"{paths.product}__brand_id": p["brand"]})
    if p.get("shop"):
        rows = rows.filter(**{f"{paths.shop}_id": p["shop"]})
    if p.get("salesperson"):
        rows = rows.filter(**{f"{paths.salesperson}_id": p["salesperson"]})
    return rows


def invoice_lines(ctx: Context) -> QuerySet[InvoiceLine]:
    rows = InvoiceLine.objects.filter(invoice__status=ISSUED)
    return _narrow(rows, ctx, INVOICE)


def credit_lines(ctx: Context) -> QuerySet[CreditNoteLine]:
    rows = CreditNoteLine.objects.filter(credit_note__status=ISSUED)
    return _narrow(rows, ctx, CREDIT)


def product_value(product: str, field: str, output_field: Any) -> Subquery:
    """A field of a line's product (``product``: the path to it), looked up per line rather than
    joined: a join with the products makes PostgreSQL misjudge how many lines match and read
    every line of the distributor instead of the period's (``make perf``, ADR-051)."""
    return Subquery(
        Product.objects.filter(pk=OuterRef(f"{product}_id")).order_by().values(field)[:1],
        output_field=output_field,
    )


def today_cost(product: str) -> Subquery:
    """Today's cost price of a line's product."""
    return product_value(product, "cost_price", MONEY)


def _figures(rows: QuerySet[Any], paths: Paths, key: Any, *, costs: bool) -> QuerySet[Any]:
    """Per key: quantity, taxable value, GST, total; with ``costs``, also the cost (recorded or
    today's), the taxable value of lines with a cost, and how many lines were estimated or had no
    cost. Costs are only worked out when shown."""
    sums: dict[str, Any] = {
        "qty": Sum("quantity"),
        "taxable": Sum("taxable_value"),
        "tax": Sum(F("cgst_amount") + F("sgst_amount") + F("igst_amount") + F("cess_amount")),
        "total": Sum("line_total"),
    }
    if not costs:
        found: QuerySet[Any] = rows.annotate(key=key).values("key").annotate(**sums).order_by()
        return found
    recorded = F(paths.unit_cost)
    today = today_cost(paths.product)
    cost = Coalesce(recorded, today)
    has_cost = IsNull(cost, False)
    estimated = IsNull(recorded, True) & IsNull(today, False)
    found = (
        rows.annotate(key=key)
        .values("key")
        .annotate(
            **sums,
            cost=Sum(ExpressionWrapper(cost * F("quantity"), output_field=MONEY)),
            costed_taxable=Sum(
                Case(When(has_cost, then=F("taxable_value")), default=Value(ZERO)),
                output_field=MONEY,
            ),
            estimated=Count(Case(When(estimated, then=1), output_field=IntegerField())),
            uncosted=Count(Case(When(IsNull(cost, True), then=1), output_field=IntegerField())),
        )
        .order_by()
    )
    return found


@dataclass
class Figures:
    qty: Decimal = ZERO
    taxable: Decimal = ZERO
    tax: Decimal = ZERO
    total: Decimal = ZERO
    cost: Decimal = ZERO
    costed_taxable: Decimal = ZERO
    estimated: int = 0
    uncosted: int = 0
    invoices: int = 0
    billed: Decimal = ZERO
    credited: Decimal = ZERO

    def add(self, row: dict[str, Any], sign: int) -> None:
        for name in ("qty", "taxable", "tax", "total", "cost", "costed_taxable"):
            setattr(self, name, getattr(self, name) + sign * (row.get(name) or ZERO))
        self.estimated += row.get("estimated") or 0
        self.uncosted += row.get("uncosted") or 0
        if sign > 0:
            self.billed += row["total"] or ZERO
        else:
            self.credited += row["total"] or ZERO

    def merge(self, other: Figures) -> None:
        """Fold another group's figures into this one (its invoices may overlap: not counted)."""
        for name in (
            "qty", "taxable", "tax", "total", "cost", "costed_taxable", "billed", "credited",
        ):  # fmt: skip
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.estimated += other.estimated
        self.uncosted += other.uncosted

    @property
    def margin(self) -> Decimal:
        return self.costed_taxable - self.cost

    @property
    def margin_pct(self) -> Decimal | None:
        return self.margin * 100 / self.costed_taxable if self.costed_taxable else None


def grouped(
    ctx: Context,
    invoice_key: Any,
    credit_key: Any,
    *,
    costs: bool | None = None,
    counts: bool = True,
) -> dict[Any, Figures]:
    """Invoices minus credit notes, per key; plus how many invoices each key had (unless
    ``counts`` is off: a distinct count costs more than the sums). Costs as the scope allows,
    unless ``costs`` says otherwise."""
    with_costs = ctx.scope.costs if costs is None else costs
    out: dict[Any, Figures] = defaultdict(Figures)
    for row in _figures(invoice_lines(ctx), INVOICE, invoice_key, costs=with_costs):
        out[row["key"]].add(row, +1)
    for row in _figures(credit_lines(ctx), CREDIT, credit_key, costs=with_costs):
        out[row["key"]].add(row, -1)
    if not counts:
        return out
    counts_found = (
        invoice_lines(ctx)
        .annotate(key=invoice_key)
        .values("key")
        .annotate(n=Count("invoice_id", distinct=True))
        .order_by()
    )
    for row in counts_found:
        out[row["key"]].invoices = row["n"]
    return out


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _amounts(f: Figures, whole: Decimal) -> dict[str, Any]:
    return {
        "qty": f.qty,
        "invoices": f.invoices,
        "taxable": _money(f.taxable),
        "tax": _money(f.tax),
        "total": _money(f.total),
        "share": f.total * 100 / whole if whole else None,
        "cost": _money(f.cost),
        "margin": _money(f.margin),
        "margin_pct": f.margin_pct,
    }


def _totals(groups: dict[Any, Figures]) -> dict[str, Any]:
    whole = Figures()
    for f in groups.values():
        for name in ("qty", "taxable", "tax", "total", "cost", "costed_taxable"):
            setattr(whole, name, getattr(whole, name) + getattr(f, name))
        whole.invoices += f.invoices
        whole.estimated += f.estimated
        whole.uncosted += f.uncosted
        whole.billed += f.billed
        whole.credited += f.credited
    return {
        **_amounts(whole, whole.total),
        "share": Decimal("100") if whole.total else None,
        "billed": _money(whole.billed),
        "credited": _money(whole.credited),
    }


def cost_notes(groups: dict[Any, Figures]) -> list[str]:
    estimated = sum(f.estimated for f in groups.values())
    uncosted = sum(f.uncosted for f in groups.values())
    notes = []
    if estimated:
        notes.append(
            f"{estimated} line(s) had no cost recorded when invoiced: today's cost price is used "
            "(estimated)."
        )
    if uncosted:
        notes.append(f"{uncosted} line(s) have no cost price and are left out of the margin.")
    return notes


def _by_total(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (-(r["total"] or ZERO), str(r.get("name", ""))))


# --- Columns ------------------------------------------------------------------------------------

TAXABLE = Column("taxable", "Taxable value", Kind.MONEY, total=True)
TAX = Column("tax", "GST", Kind.MONEY, total=True)
TOTAL = Column("total", "Total", Kind.MONEY, total=True, width=16)
SHARE = Column("share", "Share %", Kind.PERCENT, total=True, width=10)
COST = Column("cost", "Cost", Kind.MONEY, cost=True, total=True)
MARGIN_COL = Column("margin", "Margin", Kind.MONEY, cost=True, total=True)
MARGIN_PCT = Column("margin_pct", "Margin %", Kind.PERCENT, cost=True, total=True, width=10)
INVOICES = Column("invoices", "Invoices", Kind.INT, total=True, width=10)
QTY = Column("qty", "Quantity", Kind.QTY, total=True, width=12)
MONEY_COLUMNS = (TAXABLE, TAX, TOTAL, SHARE, COST, MARGIN_COL, MARGIN_PCT)


def _cached(
    ctx: Context, name: str, invoice_key: Any, credit_key: Any, *, counts: bool = True
) -> dict[Any, Figures]:
    groups: dict[Any, Figures] = ctx.once(
        name if counts else f"{name}:uncounted",
        lambda: grouped(ctx, invoice_key, credit_key, counts=counts),
    )
    return groups


# --- By period ----------------------------------------------------------------------------------

TRUNC = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}


def _periods(start: date, end: date, by: str) -> list[date]:
    if by == "month":
        first, out = start.replace(day=1), []
        while first <= end:
            out.append(first)
            first = (first + timedelta(days=32)).replace(day=1)
        return out
    step = 7 if by == "week" else 1
    first = start - timedelta(days=start.weekday()) if by == "week" else start
    return [first + timedelta(days=i) for i in range(0, (end - first).days + 1, step)]


def _period_label(day: date, by: str) -> str:
    if by == "month":
        return f"{day:%b %Y}"
    if by == "week":
        return f"Week of {day:%d-%m-%Y}"
    return f"{day:%d-%m-%Y}"


def _period_groups(ctx: Context) -> dict[Any, Figures]:
    trunc = TRUNC[ctx.params.get("group_by", "day")]
    return _cached(ctx, "periods", trunc(INVOICE.day), trunc(CREDIT.day))


def _period_key(value: Any) -> date:
    day: date = value.date() if isinstance(value, datetime) else value
    return day


def summary_rows(ctx: Context) -> list[dict[str, Any]]:
    by = ctx.params.get("group_by", "day")
    groups = {_period_key(k): f for k, f in _period_groups(ctx).items()}
    rows = []
    for day in _periods(ctx.params["date_from"], ctx.params["date_to"], by):
        f = groups.get(day, Figures())
        rows.append(
            {
                "period": _period_label(day, by),
                "start": day,
                "invoices": f.invoices,
                "billed": _money(f.billed),
                "credited": _money(f.credited),
                "taxable": _money(f.taxable),
                "tax": _money(f.tax),
                "total": _money(f.total),
            }
        )
    return rows


register(
    Report(
        code="sales_summary",
        title="Sales summary",
        group=Group.SALES,
        description="Billed, credited and net sales per day, week or month.",
        permission=SALES,
        full="reports.sales",
        columns=(
            Column("period", "Period", width=18),
            INVOICES,
            Column("billed", "Invoices total", Kind.MONEY, total=True, width=16),
            Column("credited", "Credit notes", Kind.MONEY, total=True, width=16),
            TAXABLE,
            TAX,
            Column("total", "Net sales", Kind.MONEY, total=True, width=16),
        ),
        filters=(
            *PERIOD,
            Filter(
                "group_by",
                "By",
                FilterKind.CHOICE,
                choices=("day", "week", "month"),
                default=lambda: "day",
            ),
            CATEGORY,
            BRAND,
            SHOP,
            SALESPERSON,
        ),
        rows=summary_rows,
        totals=lambda ctx: _totals(_period_groups(ctx)),
        pdf=True,
    )
)


# --- By product, category, brand ----------------------------------------------------------------


def _products(ctx: Context, *, counts: bool = True) -> dict[Any, Figures]:
    return _cached(
        ctx, "products", F(INVOICE.product + "_id"), F(CREDIT.product + "_id"), counts=counts
    )


def product_rows(ctx: Context, *, counts: bool = True) -> list[dict[str, Any]]:
    groups = _products(ctx, counts=counts)
    whole = sum((f.total for f in groups.values()), ZERO)
    names = {
        p["id"]: p
        for p in Product.objects.filter(pk__in=groups).values(
            "id", "code", "name", "category__name", "brand__name"
        )
    }
    rows = []
    for pk, f in groups.items():
        product = names.get(pk, {})
        rows.append(
            {
                "product_id": pk,
                "code": product.get("code", ""),
                "name": product.get("name", ""),
                "category": product.get("category__name") or "",
                "brand": product.get("brand__name") or "",
                **_amounts(f, whole),
            }
        )
    return _by_total(rows)


def _category_path(categories: dict[Any, dict[str, Any]], pk: Any) -> str:
    parts, seen = [], set()
    while pk and pk in categories and pk not in seen:
        seen.add(pk)
        parts.append(categories[pk]["name"])
        pk = categories[pk]["parent_id"]
    return " > ".join(reversed(parts))


def _categories(ctx: Context) -> dict[Any, Figures]:
    return _cached(
        ctx,
        "categories",
        product_value(INVOICE.product, "category_id", UUIDField()),
        product_value(CREDIT.product, "category_id", UUIDField()),
    )


def category_rows(ctx: Context) -> list[dict[str, Any]]:
    groups = _categories(ctx)
    whole = sum((f.total for f in groups.values()), ZERO)
    categories = {c["id"]: c for c in Category.objects.values("id", "name", "parent_id")}
    rows = [
        {
            "name": _category_path(categories, pk) if pk else "No category",
            **_amounts(f, whole),
        }
        for pk, f in groups.items()
    ]
    return _by_total(rows)


def _brands(ctx: Context) -> dict[Any, Figures]:
    return _cached(
        ctx,
        "brands",
        product_value(INVOICE.product, "brand_id", UUIDField()),
        product_value(CREDIT.product, "brand_id", UUIDField()),
    )


def brand_rows(ctx: Context) -> list[dict[str, Any]]:
    groups = _brands(ctx)
    whole = sum((f.total for f in groups.values()), ZERO)
    brands = {b["id"]: b for b in Brand.objects.values("id", "name", "own_brand")}
    rows = [
        {
            "name": brands[pk]["name"] if pk in brands else "No brand",
            "own_brand": "Yes" if pk in brands and brands[pk]["own_brand"] else "No",
            **_amounts(f, whole),
        }
        for pk, f in groups.items()
    ]
    return _by_total(rows)


PRODUCT_FILTERS = (*PERIOD, CATEGORY, BRAND, SHOP, SALESPERSON)

register(
    Report(
        code="sales_by_product",
        title="Sales by product",
        group=Group.SALES,
        description="What sold, net of returns, with margins for those who can see costs.",
        permission=SALES,
        full="reports.sales",
        columns=(
            Column("code", "Code", width=14),
            Column("name", "Product", width=36),
            Column("category", "Category", width=20),
            Column("brand", "Brand", width=16),
            QTY,
            *MONEY_COLUMNS,
        ),
        filters=PRODUCT_FILTERS,
        rows=product_rows,
        totals=lambda ctx: _totals(_products(ctx)),
        notes=lambda ctx: cost_notes(_products(ctx)) if ctx.scope.costs else [],
    )
)
register(
    Report(
        code="sales_by_category",
        title="Sales by category",
        group=Group.SALES,
        description="Sales per category (as set on each product), net of returns.",
        permission=SALES,
        full="reports.sales",
        columns=(Column("name", "Category", width=36), *MONEY_COLUMNS),
        filters=PRODUCT_FILTERS,
        rows=category_rows,
        totals=lambda ctx: _totals(_categories(ctx)),
        notes=lambda ctx: cost_notes(_categories(ctx)) if ctx.scope.costs else [],
    )
)
register(
    Report(
        code="sales_by_brand",
        title="Sales by brand",
        group=Group.SALES,
        description="Sales per brand, your own brands marked, net of returns.",
        permission=SALES,
        full="reports.sales",
        columns=(
            Column("name", "Brand", width=24),
            Column("own_brand", "Own brand", width=10),
            *MONEY_COLUMNS,
        ),
        filters=PRODUCT_FILTERS,
        rows=brand_rows,
        totals=lambda ctx: _totals(_brands(ctx)),
        notes=lambda ctx: cost_notes(_brands(ctx)) if ctx.scope.costs else [],
    )
)


# --- By shop and salesperson --------------------------------------------------------------------


def _shops(ctx: Context, *, counts: bool = True) -> dict[Any, Figures]:
    return _cached(ctx, "shops", F(INVOICE.shop + "_id"), F(CREDIT.shop + "_id"), counts=counts)


def shop_rows(ctx: Context, *, counts: bool = True) -> list[dict[str, Any]]:
    groups = _shops(ctx, counts=counts)
    whole = sum((f.total for f in groups.values()), ZERO)
    shops = {
        s["id"]: s
        for s in Retailer.objects.filter(pk__in=groups).values(
            "id", "code", "shop_name", "salesperson__full_name"
        )
    }
    last = dict(
        invoice_lines(ctx)
        .values("invoice__retailer_id")
        .annotate(last=Max("invoice__invoice_date"))
        .values_list("invoice__retailer_id", "last")
        .order_by()
    )
    rows = []
    for pk, f in groups.items():
        shop = shops.get(pk, {})
        rows.append(
            {
                "retailer_id": pk,
                "code": shop.get("code", ""),
                "name": shop.get("shop_name", ""),
                "salesperson": shop.get("salesperson__full_name") or "",
                "last_invoice": last.get(pk),
                **_amounts(f, whole),
            }
        )
    return _by_total(rows)


def _salespeople(ctx: Context) -> dict[Any, Figures]:
    return _cached(
        ctx, "salespeople", F(INVOICE.salesperson + "_id"), F(CREDIT.salesperson + "_id")
    )


def salesperson_rows(ctx: Context) -> list[dict[str, Any]]:
    groups = _salespeople(ctx)
    whole = sum((f.total for f in groups.values()), ZERO)
    names = dict(
        User.objects.filter(pk__in=[k for k in groups if k]).values_list("id", "full_name")
    )
    shops = dict(
        invoice_lines(ctx)
        .values(INVOICE.salesperson + "_id")
        .annotate(n=Count("invoice__retailer_id", distinct=True))
        .values_list(INVOICE.salesperson + "_id", "n")
        .order_by()
    )
    rows = [
        {
            "user_id": pk,
            "name": names.get(pk, "") if pk else "No salesperson",
            "shops": shops.get(pk, 0),
            **_amounts(f, whole),
        }
        for pk, f in groups.items()
    ]
    return _by_total(rows)


register(
    Report(
        code="sales_by_shop",
        title="Sales by shop",
        group=Group.SALES,
        description="Sales per shop, net of returns, with each shop's last bill.",
        permission=SALES,
        full="reports.sales",
        columns=(
            Column("code", "Code", width=12),
            Column("name", "Shop", width=30),
            Column("salesperson", "Salesperson", width=20),
            INVOICES,
            TAXABLE,
            TAX,
            TOTAL,
            SHARE,
            Column("last_invoice", "Last bill", Kind.DATE, width=12),
        ),
        filters=(*PERIOD, SALESPERSON, CATEGORY, BRAND),
        rows=shop_rows,
        totals=lambda ctx: _totals(_shops(ctx)),
    )
)
register(
    Report(
        code="sales_by_salesperson",
        title="Sales by salesperson",
        group=Group.SALES,
        description="Sales per salesperson (the shop's salesperson when the order was placed).",
        permission=SALES,
        full="reports.sales",
        columns=(
            Column("name", "Salesperson", width=24),
            Column("shops", "Shops", Kind.INT, width=8),
            INVOICES,
            TAXABLE,
            TAX,
            TOTAL,
            SHARE,
        ),
        filters=(*PERIOD, CATEGORY, BRAND),
        rows=salesperson_rows,
        totals=lambda ctx: _totals(_salespeople(ctx)),
    )
)


# --- Own brand vs traded margin (costs.view) ----------------------------------------------------


def _own_vs_traded(ctx: Context) -> dict[Any, Figures]:
    """The per-product figures folded into own brand (True) and traded (False): one grouped
    query and a small lookup of which products are own brand, instead of grouping every line by
    its product's brand (``make perf``: 1.35 s against 0.1 s)."""
    products = _products(ctx, counts=False)
    own = dict(Product.objects.filter(pk__in=list(products)).values_list("id", "brand__own_brand"))
    groups: dict[Any, Figures] = defaultdict(Figures)
    for pk, figures in products.items():
        groups[bool(own.get(pk))].merge(figures)
    return groups


def _margin_groups(ctx: Context) -> dict[Any, Figures]:
    by = ctx.params.get("group_by", "type")
    if by == "brand":
        return _brands(ctx)
    if by == "product":
        return _products(ctx)
    groups: dict[Any, Figures] = ctx.once("own", lambda: _own_vs_traded(ctx))
    return groups


def margin_rows(ctx: Context) -> list[dict[str, Any]]:
    by = ctx.params.get("group_by", "type")
    if by == "brand":
        rows = brand_rows(ctx)
    elif by == "product":
        own = dict(
            Product.objects.filter(pk__in=_products(ctx)).values_list("id", "brand__own_brand")
        )
        rows = [
            {**r, "own_brand": "Yes" if own.get(r["product_id"]) else "No"}
            for r in product_rows(ctx)
        ]
    else:
        groups = _margin_groups(ctx)
        whole = sum((f.total for f in groups.values()), ZERO)
        rows = [
            {
                "name": "Own brand" if own else "Traded",
                "own_brand": "Yes" if own else "No",
                **_amounts(f, whole),
            }
            for own, f in sorted(groups.items(), key=lambda kv: not kv[0])
        ]
        return rows
    return sorted(rows, key=lambda r: (r["own_brand"] != "Yes", -(r["margin"] or ZERO)))


register(
    Report(
        code="margin_own_vs_traded",
        title="Margin: own brand vs traded",
        group=Group.SALES,
        description="Taxable sales, cost and margin of your own brands against traded goods.",
        permission=MARGIN,
        full="reports.sales",
        columns=(
            Column("name", "Name", width=36),
            Column("own_brand", "Own brand", width=10),
            TAXABLE,
            COST,
            MARGIN_COL,
            MARGIN_PCT,
            SHARE,
        ),
        filters=(
            *PERIOD,
            Filter(
                "group_by",
                "By",
                FilterKind.CHOICE,
                choices=("type", "brand", "product"),
                default=lambda: "type",
            ),
            CATEGORY,
        ),
        rows=margin_rows,
        totals=lambda ctx: _totals(_margin_groups(ctx)),
        notes=lambda ctx: cost_notes(_margin_groups(ctx)),
    )
)


# --- By invoice: the sales register -------------------------------------------------------------
# One row per invoice and per credit note (as a minus), with the document's own totals (its total
# includes the round-off), as issued: the buyer's name and GSTIN from the document. One query for
# both kinds (a UNION), so a page is read with LIMIT and an export streams in chunks.

REGISTER = (
    "day", "doc_number", "doc_type", "shop_code", "shop_name", "gstin", "place",
    "taxable", "cgst", "sgst", "igst", "cess", "total", "salesperson", "doc_id", "retailer_ref",
)  # fmt: skip
DOC_TYPES = {"INVOICE": "Invoice", "CREDIT_NOTE": "Credit note"}
_AMOUNTS = {
    "taxable": "taxable_total",
    "cgst": "cgst_total",
    "sgst": "sgst_total",
    "igst": "igst_total",
    "cess": "cess_total",
    "total": "grand_total",
}


def _register_documents(ctx: Context, model: Any, day: str, salesperson: str) -> QuerySet[Any]:
    p = ctx.params
    rows: QuerySet[Any] = ctx.shops(
        model.objects.filter(
            status=ISSUED, **{f"{day}__gte": p["date_from"], f"{day}__lte": p["date_to"]}
        )
    )
    if p.get("shop"):
        rows = rows.filter(retailer_id=p["shop"])
    if p.get("salesperson"):
        rows = rows.filter(**{f"{salesperson}_id": p["salesperson"]})
    return rows


def _register_invoices(ctx: Context) -> QuerySet[Any]:
    return _register_documents(ctx, Invoice, "invoice_date", "order__salesperson")


def _register_notes(ctx: Context) -> QuerySet[Any]:
    return _register_documents(ctx, CreditNote, "note_date", "invoice__order__salesperson")


def _line_figures(prefix: str) -> dict[str, Any]:
    """Per line: its cost at the recorded cost, else today's (credit notes at their invoice
    lines' cost; value-only notes have no quantity, so no cost), and its margin, only for lines
    with a cost (lines with none are left out of the margin, as in the other sales reports)."""
    unit = Coalesce(F(f"{prefix}unit_cost"), today_cost(f"{prefix}product"))
    cost = ExpressionWrapper(unit * F("quantity"), output_field=MONEY)
    margin = Case(
        When(
            IsNull(unit, False),
            then=ExpressionWrapper(F("taxable_value") - unit * F("quantity"), output_field=MONEY),
        ),
        output_field=MONEY,
    )
    return {"cost": Sum(cost), "margin": Sum(margin)}


def _register_values(
    rows: QuerySet[Any], kind: str, sign: int, day: str, salesperson: str
) -> QuerySet[Any]:
    """The register's columns for one kind of document (credit notes as minus amounts)."""
    fields: dict[str, Any] = {
        "day": F(day),
        "doc_number": F("number"),
        "doc_type": Value(kind),
        "shop_code": KT("buyer__code"),
        "shop_name": KT("buyer__name"),
        "gstin": KT("buyer__gstin"),
        "place": F("place_of_supply__name"),
        **{
            key: ExpressionWrapper(F(field) * sign, output_field=MONEY)
            for key, field in _AMOUNTS.items()
        },
        "salesperson": F(f"{salesperson}__full_name"),
        "doc_id": F("id"),
        "retailer_ref": F("retailer_id"),
    }
    found: QuerySet[Any] = rows.annotate(**fields).values(*REGISTER)
    return found


def _money_per_document(model: Any, parent: str, prefix: str, ids: list[Any]) -> dict[Any, Any]:
    """Cost and margin per document, for the documents of one page or export chunk."""
    if not ids:
        return {}
    found = (
        model.objects.filter(**{f"{parent}__in": ids})
        .order_by()
        .values(parent)
        .annotate(**_line_figures(prefix))
    )
    return {r[parent]: r for r in found}


class RegisterRows:
    """The register's rows: read without costs (the database sorts and pages just the
    documents), then cost and margin for each page, or each export chunk, in two grouped
    queries, instead of working them out for every document before sorting."""

    def __init__(self, rows: QuerySet[Any], costs: bool) -> None:
        self.rows = rows
        self.costs = costs

    def count(self) -> int:
        return int(self.rows.count())

    def __getitem__(self, part: slice) -> list[dict[str, Any]]:
        return self._complete(list(self.rows[part]))

    def iterator(self, chunk_size: int = 2000) -> Iterator[dict[str, Any]]:
        chunk: list[dict[str, Any]] = []
        for row in self.rows.iterator(chunk_size=chunk_size):
            chunk.append(row)
            if len(chunk) >= chunk_size:
                yield from self._complete(chunk)
                chunk = []
        yield from self._complete(chunk)

    def _complete(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        money: dict[Any, Any] = {}
        if self.costs:
            ids = {kind: [r["doc_id"] for r in rows if r["doc_type"] == kind] for kind in DOC_TYPES}
            money = {
                **_money_per_document(InvoiceLine, "invoice_id", "", ids["INVOICE"]),
                **_money_per_document(
                    CreditNoteLine, "credit_note_id", "invoice_line__", ids["CREDIT_NOTE"]
                ),
            }
        out = []
        for row in rows:
            kind = row["doc_type"]
            sign = 1 if kind == "INVOICE" else -1
            figures = money.get(row["doc_id"]) or {}
            out.append(
                {
                    **row,
                    "doc_type": DOC_TYPES[kind],
                    "cost": None if figures.get("cost") is None else sign * figures["cost"],
                    "margin": None if figures.get("margin") is None else sign * figures["margin"],
                    "invoice_id" if kind == "INVOICE" else "credit_note_id": row["doc_id"],
                    "retailer_id": row["retailer_ref"],
                }
            )
        return out


def register_rows(ctx: Context) -> RegisterRows:
    invoices = _register_values(
        _register_invoices(ctx), "INVOICE", 1, "invoice_date", "order__salesperson"
    )
    notes = _register_values(
        _register_notes(ctx), "CREDIT_NOTE", -1, "note_date", "invoice__order__salesperson"
    )
    union = invoices.union(notes, all=True).order_by("day", "doc_number")
    return RegisterRows(union, ctx.scope.costs)


def _register_totals(ctx: Context) -> dict[str, Any]:
    def sums(rows: QuerySet[Any]) -> dict[str, Decimal]:
        found = rows.aggregate(**{key: Sum(field) for key, field in _AMOUNTS.items()})
        return {key: found[key] or ZERO for key in _AMOUNTS}

    def money_of(rows: QuerySet[Any], prefix: str) -> dict[str, Decimal]:
        found = rows.aggregate(**_line_figures(prefix))
        return {key: Decimal(found[key] or ZERO) for key in ("cost", "margin")}

    billed, credited = sums(_register_invoices(ctx)), sums(_register_notes(ctx))
    out: dict[str, Any] = {key: billed[key] - credited[key] for key in _AMOUNTS}
    if ctx.scope.costs:
        # The sales facts' own lines: the same documents (issued, in the period, own shops, shop
        # and salesperson), filtered through the join, which PostgreSQL starts from the period.
        sold = money_of(invoice_lines(ctx), "")
        returned = money_of(credit_lines(ctx), "invoice_line__")
        out.update({key: sold[key] - returned[key] for key in ("cost", "margin")})
    return out


register(
    Report(
        code="sales_by_invoice",
        title="Sales by invoice",
        group=Group.SALES,
        description="The sales register: every invoice and credit note in the period, one per row.",
        permission=SALES,
        full="reports.sales",
        columns=(
            Column("day", "Date", Kind.DATE, width=12),
            Column("doc_number", "Number", width=20),
            Column("doc_type", "Type", width=12),
            Column("shop_code", "Shop code", width=12),
            Column("shop_name", "Shop", width=30),
            Column("gstin", "GSTIN", width=18),
            Column("place", "Place of supply", width=18),
            TAXABLE,
            Column("cgst", "CGST", Kind.MONEY, total=True),
            Column("sgst", "SGST", Kind.MONEY, total=True),
            Column("igst", "IGST", Kind.MONEY, total=True),
            Column("cess", "Cess", Kind.MONEY, total=True),
            TOTAL,
            Column("salesperson", "Salesperson", width=20),
            COST,
            MARGIN_COL,
        ),
        filters=(*PERIOD, SHOP, SALESPERSON),
        rows=register_rows,
        totals=lambda ctx: ctx.once("register_totals", lambda: _register_totals(ctx)),
        notes=lambda ctx: [
            "Credit notes are shown as minus amounts. Each total includes its round-off.",
            *(
                [
                    "Cost is what each invoice line recorded when issued; bills from before that "
                    "use today's cost price (estimated). Lines with no cost price are left out "
                    "of the margin."
                ]
                if ctx.scope.costs
                else []
            ),
        ],
    )
)
