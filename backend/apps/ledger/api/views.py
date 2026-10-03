"""Receivables, ageing, a shop's statement and dues, adjustments (PLAN §3.10, ADR-046 items
8-10). Sales staff limited to their own shops see only those shops."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import Q
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.billing.tax import fy_start
from apps.ledger import selectors
from apps.ledger import services as ledger
from apps.ledger.api import serializers as s
from apps.ledger.models import LedgerAdjustment
from apps.retailers.models import Retailer
from apps.retailers.selectors import retailer_for, retailers_for
from common.dates import today_ist
from common.errors import InvalidFields, NotFound
from common.idempotency import idempotent
from common.numbers import fill
from common.permissions import HasPermission

VIEW = "ledger.view"
IDEMPOTENCY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, True)
TAGS = ["receivables"]
BUCKETS = ("not_due", "d0_30", "d31_60", "d61_90", "d90_plus")


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


def _date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidFields({field: [_("Use YYYY-MM-DD.")]}) from exc


def _int(value: str | None, field: str, default: int, maximum: int) -> int:
    if not value:
        return default
    if not value.isdigit() or not 1 <= int(value) <= maximum:
        raise InvalidFields(
            {field: [fill(_("Use a number from 1 to %(maximum)s."), {"maximum": maximum})]}
        )
    return int(value)


class Guarded(APIView):
    permission_classes = [HasPermission]


def _shop(request: Request, retailer_id: UUID) -> Retailer:
    shop = retailer_for(_user(request), retailer_id)
    if shop is None:
        raise NotFound()
    return shop


RECEIVABLE_FILTERS = [
    OpenApiParameter("search", str, description="Shop name, code or mobile"),
    OpenApiParameter("salesperson", UUID),
    OpenApiParameter("overdue", bool, description="Only shops with something overdue"),
    OpenApiParameter("page", int),
    OpenApiParameter("page_size", int),
]


def _receivables(request: Request, basis: str | None = None) -> dict[str, Any]:
    q = request.query_params
    shops = retailers_for(_user(request))
    term = q.get("search", "").strip()
    if term:
        shops = shops.filter(
            Q(shop_name__icontains=term) | Q(code__iexact=term) | Q(mobile__icontains=term)
        )
    if q.get("salesperson"):
        try:
            shops = shops.filter(salesperson_id=UUID(q["salesperson"]))
        except ValueError as exc:
            raise InvalidFields({"salesperson": [_("Not a valid id.")]}) from exc
    used, rows = selectors.receivable_rows(list(shops.values_list("pk", flat=True)), basis=basis)
    if q.get("overdue", "").lower() in ("1", "true", "yes"):
        rows = [row for row in rows if row["overdue"] > 0]
    page = _int(q.get("page"), "page", 1, 100000)
    size = _int(q.get("page_size"), "page_size", 50, 200)
    zero = Decimal("0.00")
    totals = {
        "buckets": {b: sum((row["buckets"][b] for row in rows), zero) for b in BUCKETS},
        "owed": sum((row["owed"] for row in rows), zero),
        "overdue": sum((row["overdue"] for row in rows), zero),
        "unapplied_credit": sum((row["unapplied_credit"] for row in rows), zero),
        "net": sum((row["net"] for row in rows), zero),
        "shops": len(rows),
    }
    return {
        "basis": used,
        "totals": totals,
        "count": len(rows),
        "page": page,
        "page_size": size,
        "results": rows[(page - 1) * size : page * size],
    }


class ReceivablesView(Guarded):
    required_permission = VIEW

    @extend_schema(
        operation_id="receivables_list",
        tags=TAGS,
        parameters=RECEIVABLE_FILTERS,
        responses=s.ReceivablesPageSerializer,
    )
    def get(self, request: Request) -> Response:
        return Response(s.ReceivablesPageSerializer(_receivables(request)).data)


class AgeingView(Guarded):
    required_permission = VIEW

    @extend_schema(
        operation_id="receivables_ageing",
        tags=TAGS,
        parameters=[
            *RECEIVABLE_FILTERS,
            OpenApiParameter(
                "basis",
                str,
                enum=["INVOICE_DATE", "DUE_DATE"],
                description="Defaults to the receivables.ageing_basis setting",
            ),
        ],
        responses=s.ReceivablesPageSerializer,
    )
    def get(self, request: Request) -> Response:
        basis = request.query_params.get("basis") or None
        if basis not in (None, "INVOICE_DATE", "DUE_DATE"):
            raise InvalidFields({"basis": [_("Use INVOICE_DATE or DUE_DATE.")]})
        return Response(s.ReceivablesPageSerializer(_receivables(request, basis)).data)


class ReceivablesSummaryView(Guarded):
    required_permission = VIEW

    @extend_schema(
        operation_id="receivables_summary", tags=TAGS, responses=s.ReceivablesSummarySerializer
    )
    def get(self, request: Request) -> Response:
        from apps.payments import selectors as payment_selectors

        user = _user(request)
        ids = list(retailers_for(user).values_list("pk", flat=True))
        body = selectors.receivables_summary(ids)
        body["collections_pending_handover"] = (
            payment_selectors.pending_handover_total()
            if user.has_permission_code("payments.record")
            else None
        )
        return Response(s.ReceivablesSummarySerializer(body).data)


class RetailerLedgerView(Guarded):
    required_permission = VIEW

    @extend_schema(
        operation_id="retailers_ledger",
        tags=TAGS,
        parameters=[
            OpenApiParameter("date_from", date, description="Defaults to 90 days ago"),
            OpenApiParameter("date_to", date, description="Defaults to today"),
        ],
        responses=s.StatementSerializer,
    )
    def get(self, request: Request, retailer_id: UUID) -> Response:
        shop = _shop(request, retailer_id)
        return Response(s.StatementSerializer(statement_for(shop, request)).data)


def statement_for(shop: Retailer, request: Request) -> dict[str, Any]:
    """Shared with the shop's own statement."""
    q = request.query_params
    today = today_ist()
    date_to = _date(q.get("date_to"), "date_to") or today
    date_from = _date(q.get("date_from"), "date_from") or date_to - timedelta(days=90)
    if date_from > date_to:
        raise InvalidFields({"date_from": [_("The start is after the end.")]})
    if (date_to - date_from).days > 731:
        raise InvalidFields({"date_from": [_("Choose at most two years.")]})
    found = selectors.statement(shop.pk, date_from, date_to)
    return {
        "retailer": shop,
        "position": selectors.outstanding(shop.pk),
        "credit_held_while_advances_off": selectors.credit_held_while_advances_off(shop.pk),
        "credit_limit": shop.credit_limit,
        "date_from": found.date_from,
        "date_to": found.date_to,
        "opening_balance": found.opening_balance,
        "lines": found.lines,
        "total_debits": found.total_debits,
        "total_credits": found.total_credits,
        "closing_balance": found.closing_balance,
    }


class RetailerDuesView(Guarded):
    """What the shop owes (earliest due first) and its unused money: for recording a payment and
    choosing what it pays, or matching credit by hand."""

    required_permission = VIEW

    @extend_schema(operation_id="retailers_dues", tags=TAGS, responses=s.DuesSerializer)
    def get(self, request: Request, retailer_id: UUID) -> Response:
        shop = _shop(request, retailer_id)
        body = {
            "position": selectors.outstanding(shop.pk),
            "credit_held_while_advances_off": selectors.credit_held_while_advances_off(shop.pk),
            "financial_year_start": fy_start(today_ist()),
            "dues": selectors.open_dues([shop.pk]),
            "unused_money": selectors.open_money(shop.pk),
        }
        return Response(s.DuesSerializer(body).data)


class AdjustmentsView(Guarded):
    required_permission = "ledger.adjust"

    @extend_schema(
        operation_id="ledger_adjustments_create",
        tags=TAGS,
        request=s.LedgerAdjustmentCreateSerializer,
        responses={201: s.LedgerAdjustmentSerializer},
        parameters=[IDEMPOTENCY],
    )
    @idempotent("ledger.adjustments.create")
    def post(self, request: Request) -> Response:
        data = s.LedgerAdjustmentCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        shop = _shop(request, v["retailer"])
        if v["date"] > today_ist():
            raise InvalidFields({"date": [_("The date can't be in the future.")]})
        adjustment: LedgerAdjustment = ledger.post_adjustment(
            shop.pk,
            v["kind"],
            v["amount"],
            on=v["date"],
            narration=v["narration"],
            by=_user(request),
            due_date=v["due_date"],
            bill_number=v["bill_number"],
        )
        return Response(s.LedgerAdjustmentSerializer(adjustment).data, status=201)
