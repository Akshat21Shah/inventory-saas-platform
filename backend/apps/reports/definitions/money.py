"""Money reports (ADR-050 items 8 and 10): receivables ageing, collections and salesperson
collections. Open to the financial reports, and to sales staff for their own shops when the
distributor shows them only their own shops."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from django.db.models import Count, F, Max, Min, Q, Sum
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.models import User
from apps.ledger.selectors import BUCKETS, ageing
from apps.payments.models import Payment
from apps.reports.registry import (
    PERIOD,
    Column,
    Context,
    Filter,
    FilterKind,
    Group,
    Kind,
    Mapped,
    Report,
    register,
)
from apps.retailers.models import Retailer
from common.permissions import AnyOf

FINANCIAL = "reports.financial"
MONEY_OR_OWN = AnyOf((FINANCIAL, "reports.sales_own"))
ZERO = Decimal("0")
COUNTED = (Payment.Status.RECEIVED, Payment.Status.CLEARED, Payment.Status.PENDING_CLEARANCE)
MODE_LABELS = dict(Payment.Mode.choices)
STATUS_LABELS = dict(Payment.Status.choices)
HANDOVER_LABELS = dict(Payment.Handover.choices)
BASIS_LABELS = {
    "INVOICE_DATE": gettext_lazy("the bill date"),
    "DUE_DATE": gettext_lazy("the due date"),
}

SALESPERSON = Filter("salesperson", "Salesperson", FilterKind.ID, entity="staff")
SHOP = Filter("shop", "Shop", FilterKind.ID, entity="shop")


def _money(value: Any) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


# --- Receivables ageing -------------------------------------------------------------------------


def _ageing(ctx: Context) -> tuple[str, list[dict[str, Any]]]:
    found: tuple[str, list[dict[str, Any]]] = ctx.once("ageing", lambda: _make_ageing(ctx))
    return found


def _make_ageing(ctx: Context) -> tuple[str, list[dict[str, Any]]]:
    shops = ctx.shops(Retailer.objects.all(), "")
    if ctx.params.get("salesperson"):
        shops = shops.filter(salesperson_id=ctx.params["salesperson"])
    info = {
        s["id"]: s
        for s in shops.values("id", "code", "shop_name", "credit_limit", "salesperson__full_name")
    }
    basis, rows = ageing(info)
    last_payment = dict(
        Payment.objects.filter(retailer_id__in=info, status__in=COUNTED)
        .values("retailer_id")
        .annotate(last=Max("payment_date"))
        .values_list("retailer_id", "last")
        .order_by()
    )
    out = []
    for row in rows:
        if ctx.params.get("overdue_only") and row.overdue <= 0:
            continue
        shop = info[row.retailer_id]
        out.append(
            {
                "retailer_id": row.retailer_id,
                "code": shop["code"],
                "name": shop["shop_name"],
                "salesperson": shop["salesperson__full_name"] or "",
                **{b: row.buckets[b] for b in BUCKETS},
                "owed": row.owed,
                "credit": row.unapplied_credit,
                "net": row.net,
                "credit_limit": shop["credit_limit"],
                "oldest_due": row.oldest_due,
                "last_payment": last_payment.get(row.retailer_id),
            }
        )
    return basis, out


def ageing_totals(ctx: Context) -> dict[str, Any]:
    _basis, rows = _ageing(ctx)
    keys = (*BUCKETS, "owed", "credit", "net")
    return {k: sum((r[k] for r in rows), ZERO) for k in keys}


register(
    Report(
        code="receivables_ageing",
        title="Receivables ageing",
        group=Group.MONEY,
        description="What each shop owes, by how long it has been owed.",
        permission=MONEY_OR_OWN,
        full=FINANCIAL,
        columns=(
            Column("code", "Code", width=12),
            Column("name", "Shop", width=30),
            Column("salesperson", "Salesperson", width=20),
            Column("not_due", "Not due", Kind.MONEY, total=True),
            Column("d0_30", "0-30 days", Kind.MONEY, total=True),
            Column("d31_60", "31-60 days", Kind.MONEY, total=True),
            Column("d61_90", "61-90 days", Kind.MONEY, total=True),
            Column("d90_plus", "Over 90 days", Kind.MONEY, total=True),
            Column("owed", "Owed", Kind.MONEY, total=True, width=16),
            Column("credit", "Credit with us", Kind.MONEY, total=True),
            Column("net", "Balance", Kind.MONEY, total=True, width=16),
            Column("credit_limit", "Credit limit", Kind.MONEY),
            Column("oldest_due", "Oldest due", Kind.DATE, width=12),
            Column("last_payment", "Last payment", Kind.DATE, width=12),
        ),
        filters=(SALESPERSON, Filter("overdue_only", "Overdue only", FilterKind.BOOL)),
        rows=lambda ctx: _ageing(ctx)[1],
        totals=ageing_totals,
        notes=lambda ctx: [
            _("Aged from %(basis)s.")
            % {"basis": BASIS_LABELS.get(_ageing(ctx)[0], _ageing(ctx)[0])}
        ],
        pdf=True,
    )
)


# --- Collections --------------------------------------------------------------------------------


def _payments(ctx: Context) -> Any:
    p = ctx.params
    rows = ctx.shops(
        Payment.objects.filter(payment_date__gte=p["date_from"], payment_date__lte=p["date_to"])
    )
    for key, field in (
        ("mode", "mode"),
        ("status", "status"),
        ("collected_by", "collected_by_id"),
        ("shop", "retailer_id"),
    ):
        if p.get(key):
            rows = rows.filter(**{field: p[key]})
    return rows


def collection_rows(ctx: Context) -> Mapped:
    values = (
        _payments(ctx)
        .values(
            "payment_date",
            "number",
            "mode",
            "amount",
            "status",
            "handover_status",
            "reference_no",
            "cheque_number",
            "retailer_id",
            payment_id=F("id"),
            shop=F("retailer__shop_name"),
            collector=F("collected_by__full_name"),
        )
        .order_by("-payment_date", "-number")
    )
    return Mapped(
        values,
        lambda r: {
            **r,
            "mode": MODE_LABELS.get(r["mode"], r["mode"]),
            "status": STATUS_LABELS.get(r["status"], r["status"]),
            "handover": HANDOVER_LABELS.get(r["handover_status"], ""),
            "reference": r["cheque_number"] or r["reference_no"],
            "collector": r["collector"] or "",
        },
    )


def collection_totals(ctx: Context) -> dict[str, Any]:
    found = _payments(ctx).filter(status__in=COUNTED).aggregate(amount=Sum("amount"))
    return {"amount": found["amount"] or ZERO}


def collection_notes(ctx: Context) -> list[str]:
    by_mode = (
        _payments(ctx)
        .filter(status__in=COUNTED)
        .values("mode")
        .annotate(total=Sum("amount"))
        .order_by("mode")
    )
    parts = [f"{MODE_LABELS.get(r['mode'], r['mode'])} ₹{_money(r['total']):,}" for r in by_mode]
    notes = ["Bounced and reversed payments are listed but not added to the total."]
    if parts:
        notes.insert(0, "By mode: " + ", ".join(parts) + ".")
    return notes


register(
    Report(
        code="collections",
        title="Collections",
        group=Group.MONEY,
        description="Every payment received in the period, by mode and who collected it.",
        permission=MONEY_OR_OWN,
        full=FINANCIAL,
        columns=(
            Column("payment_date", "Date", Kind.DATE, width=12),
            Column("number", "Receipt", width=16),
            Column("shop", "Shop", width=28),
            Column("mode", "Mode", width=14),
            Column("amount", "Amount", Kind.MONEY, total=True, width=16),
            Column("status", "Status", width=20),
            Column("collector", "Collected by", width=18),
            Column("handover", "Handover", width=16),
            Column("reference", "Reference / cheque", width=20),
        ),
        filters=(
            *PERIOD,
            Filter("mode", "Mode", FilterKind.CHOICE, choices=tuple(Payment.Mode.values)),
            Filter("status", "Status", FilterKind.CHOICE, choices=tuple(Payment.Status.values)),
            Filter("collected_by", "Collected by", FilterKind.ID, entity="staff"),
            SHOP,
        ),
        rows=collection_rows,
        totals=collection_totals,
        notes=collection_notes,
        pdf=True,
    )
)


# --- Salesperson collections --------------------------------------------------------------------


def _salesperson_rows(ctx: Context) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = ctx.once("salesperson_collections", lambda: _make(ctx))
    return rows


def _make(ctx: Context) -> list[dict[str, Any]]:
    p = ctx.params
    period = Payment.objects.filter(
        payment_date__gte=p["date_from"], payment_date__lte=p["date_to"], status__in=COUNTED
    )
    collected = (
        period.filter(collected_by__isnull=False)
        .values("collected_by_id")
        .annotate(
            count=Count("id"),
            cash=Sum("amount", filter=Q(mode=Payment.Mode.CASH)),
            cheque=Sum("amount", filter=Q(mode=Payment.Mode.CHEQUE)),
            upi=Sum("amount", filter=Q(mode=Payment.Mode.UPI)),
            total=Sum("amount"),
            handed_over=Sum("amount", filter=Q(handover_status=Payment.Handover.HANDED_OVER)),
        )
        .order_by()
    )
    # Still with the salesman, whenever collected (the handover report's figure today).
    pending = {
        r["collected_by_id"]: r
        for r in Payment.objects.filter(
            handover_status=Payment.Handover.WITH_SALESMAN, status__in=COUNTED
        )
        .values("collected_by_id")
        .annotate(amount=Sum("amount"), oldest=Min("payment_date"))
        .order_by()
    }
    from_shops = dict(
        period.filter(retailer__salesperson__isnull=False)
        .values("retailer__salesperson_id")
        .annotate(total=Sum("amount"))
        .values_list("retailer__salesperson_id", "total")
        .order_by()
    )
    people: dict[Any, dict[str, Any]] = defaultdict(dict)
    for r in collected:
        people[r["collected_by_id"]].update(r)
    for person in [*pending, *from_shops]:  # also those who only hold money or have shops
        people.setdefault(person, {})
    if ctx.scope.own_shops:
        people = defaultdict(dict, {k: v for k, v in people.items() if k == ctx.scope.user_id})
    names = dict(User.objects.filter(pk__in=list(people)).values_list("id", "full_name"))
    out = []
    for pk, r in people.items():
        out.append(
            {
                "user_id": pk,
                "name": names.get(pk, ""),
                "count": r.get("count", 0),
                "cash": r.get("cash") or ZERO,
                "cheque": r.get("cheque") or ZERO,
                "upi": r.get("upi") or ZERO,
                "total": r.get("total") or ZERO,
                "handed_over": r.get("handed_over") or ZERO,
                "with_salesman": pending.get(pk, {}).get("amount") or ZERO,
                "oldest_pending": pending.get(pk, {}).get("oldest"),
                "from_shops": from_shops.get(pk) or ZERO,
            }
        )
    out.sort(key=lambda r: (-r["total"], r["name"]))
    return out


register(
    Report(
        code="salesperson_collections",
        title="Salesperson collections",
        group=Group.MONEY,
        description="What each salesperson collected, handed over and still holds.",
        permission=MONEY_OR_OWN,
        full=FINANCIAL,
        columns=(
            Column("name", "Salesperson", width=24),
            Column("count", "Collections", Kind.INT, total=True, width=10),
            Column("cash", "Cash", Kind.MONEY, total=True),
            Column("cheque", "Cheque", Kind.MONEY, total=True),
            Column("upi", "UPI", Kind.MONEY, total=True),
            Column("total", "Collected", Kind.MONEY, total=True, width=16),
            Column("handed_over", "Handed over", Kind.MONEY, total=True),
            Column("with_salesman", "Still with them", Kind.MONEY, total=True),
            Column("oldest_pending", "Oldest not handed over", Kind.DATE, width=14),
            Column("from_shops", "Received from their shops", Kind.MONEY, total=True, width=18),
        ),
        filters=PERIOD,
        rows=_salesperson_rows,
        totals=lambda ctx: {
            k: sum((r[k] for r in _salesperson_rows(ctx)), ZERO)
            for k in (
                "count",
                "cash",
                "cheque",
                "upi",
                "total",
                "handed_over",
                "with_salesman",
                "from_shops",
            )
        },
        notes=lambda ctx: [
            _(
                "Collected: payments each salesperson collected themselves in the period. Still "
                "with them: not yet handed over, whenever collected. Received from their shops: "
                "every payment from the shops now assigned to them, by any means."
            )
        ],
    )
)
