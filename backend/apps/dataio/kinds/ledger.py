"""Opening balances import (PLAN task 5.5, ADR-046, ADR-047): what each shop owed (or had paid in
advance) when the distributor started using the platform. Shops are matched by mobile number or
shop code. A shop may have several unpaid old bills, one row each, with the bill's date and due
date (the shop's payment terms after the bill date if empty), so they age and fall overdue like
invoices; a bill number already imported for the shop is refused. An advance (a minus amount) is
once per shop. Every row is audited."""

from collections.abc import Iterable
from datetime import date
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.models import User
from apps.dataio.kinds.base import Column, RowPlan
from apps.dataio.parsing import Sheet, parse_date, parse_decimal
from apps.ledger import services as ledger
from apps.ledger.models import LedgerAdjustment
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.numbers import fill
from common.phone import normalize_indian_mobile

C = Column
COLUMNS: tuple[Column, ...] = (
    C(
        "shop",
        "Shop",
        ("mobile", "mobile number", "shop code", "retailer", "customer"),
        True,
        gettext_lazy("The shop's mobile number or code (R-00001)."),
        "9876500001",
    ),
    C(
        "amount",
        "Amount owed",
        ("balance", "opening balance", "outstanding", "due", "amount"),
        True,
        gettext_lazy(
            "What the shop owes you. Use a minus sign for money the shop paid in advance."
        ),
        "12500.00",
    ),
    C(
        "bill_number",
        "Bill number",
        ("invoice number", "bill no", "invoice no", "reference"),
        False,
        gettext_lazy(
            "The old bill's number, if known. Each bill number is imported once per shop."
        ),
        "SD/25-26/0412",
    ),
    C(
        "bill_date",
        "Bill date",
        ("as of date", "date", "balance date", "invoice date"),
        True,
        gettext_lazy("The date of the old bill, or of the advance (DD-MM-YYYY)."),
        "15-02-2026",
    ),
    C(
        "due_date",
        "Due date",
        ("due", "due on", "payment due"),
        False,
        gettext_lazy(
            "When the bill was due (DD-MM-YYYY). The shop's payment terms after the bill date if "
            "empty."
        ),
        "17-03-2026",
    ),
    C(
        "note",
        "Note",
        ("narration", "remarks", "description"),
        False,
        gettext_lazy("Shown on the shop's statement."),
        "Balance from old books",
    ),
)
LABEL = {c.name: c.label for c in COLUMNS}


def _date(plan: RowPlan, v: dict[str, str], field: str, *, required: bool) -> date | None:
    if not v.get(field):
        if required:
            plan.error(LABEL[field], _("Enter the date, like 15-02-2026."))
        return None
    try:
        day = parse_date(v[field])
    except ValueError:
        plan.error(LABEL[field], _("Use a date like 15-02-2026."))
        return None
    if field == "bill_date" and day > today_ist():
        plan.error(LABEL[field], _("The date can't be in the future."))
    return day


def _shops() -> tuple[dict[str, Retailer], dict[str, Retailer]]:
    by_mobile: dict[str, Retailer] = {}
    by_code: dict[str, Retailer] = {}
    for shop in Retailer.objects.filter(deleted_at__isnull=True):
        by_mobile[shop.mobile] = shop
        by_code[shop.code.lower()] = shop
    return by_mobile, by_code


def _find(
    text: str, by_mobile: dict[str, Retailer], by_code: dict[str, Retailer]
) -> Retailer | None:
    text = text.strip()
    if text.lower() in by_code:
        return by_code[text.lower()]
    try:
        return by_mobile.get(normalize_indian_mobile(text))
    except ValidationError:
        return None


class OpeningBalancesKind:
    code = "OPENING_BALANCES"
    label = "Opening balances"
    permission = "ledger.adjust"
    key_label = LABEL["shop"]
    columns = COLUMNS
    modes = ("ADD_ONLY",)
    restricted: dict[str, str] = {}

    def reference_lists(self) -> dict[str, list[str]]:
        return {}

    def plan(self, sheet: Sheet, mode: str, by: User) -> list[RowPlan]:
        by_mobile, by_code = _shops()
        advances = set(
            LedgerAdjustment.objects.filter(kind=LedgerAdjustment.Kind.OPENING_CREDIT).values_list(
                "retailer_id", flat=True
            )
        )
        bills = set(
            LedgerAdjustment.objects.filter(kind=LedgerAdjustment.Kind.OPENING_DEBIT)
            .exclude(bill_number="")
            .values_list("retailer_id", "bill_number")
        )
        seen_advance: dict[UUID, int] = {}
        seen_bill: dict[tuple[UUID, str], int] = {}
        plans: list[RowPlan] = []
        for row in sheet.rows:
            v = row.values
            plan = RowPlan(number=row.number, key=v.get("shop", ""))
            plans.append(plan)
            shop = _find(v["shop"], by_mobile, by_code) if v.get("shop") else None
            if not v.get("shop"):
                plan.error(LABEL["shop"], _("Enter the shop's mobile number or code."))
            elif shop is None:
                plan.error(
                    LABEL["shop"],
                    fill(_("No shop has the mobile number or code %(shop)s."), {"shop": v["shop"]}),
                )
            amount = None
            try:
                amount = parse_decimal(v.get("amount", ""), places=2)
                if amount == 0:
                    plan.action = "UNCHANGED"
            except ValueError:
                plan.error(
                    LABEL["amount"], _("Enter the amount in rupees and paise, e.g. 12500.00.")
                )
            bill_date = _date(plan, v, "bill_date", required=True)
            due = _date(plan, v, "due_date", required=False)
            if bill_date and due and due < bill_date:
                plan.error(LABEL["due_date"], _("The due date can't be before the bill date."))
            number = v.get("bill_number", "").strip()[:40]
            if shop is None or amount is None or not plan.ok or plan.action == "UNCHANGED":
                continue
            plan.key = f"{shop.code} {number}".strip()
            if amount < 0:
                if shop.pk in advances:
                    plan.error(LABEL["shop"], _("This shop already has an opening advance."))
                    continue
                if shop.pk in seen_advance:
                    plan.error(
                        LABEL["amount"],
                        fill(
                            _("This shop's advance is also in row %(value)s."),
                            {"value": seen_advance[shop.pk]},
                        ),
                    )
                    continue
                seen_advance[shop.pk] = row.number
            elif number:
                if (shop.pk, number) in bills:
                    plan.error(
                        LABEL["bill_number"], _("This bill is already in the shop's account.")
                    )
                    continue
                if (shop.pk, number) in seen_bill:
                    plan.error(
                        LABEL["bill_number"],
                        fill(
                            _("This bill is also in row %(value)s."),
                            {"value": seen_bill[shop.pk, number]},
                        ),
                    )
                    continue
                seen_bill[(shop.pk, number)] = row.number
            plan.action = "NEW"
            plan.target_id = shop.pk
            what = "Opening advance" if amount < 0 else f"Old bill {number}".strip()
            plan.changes = {what: ["", f"{abs(amount):.2f}"]}
            plan.data = {
                "retailer_id": shop.pk,
                "amount": amount,
                "bill_date": bill_date,
                "due_date": due,
                "bill_number": number,
                "note": v.get("note", "").strip() or "Opening balance (import)",
            }
        return plans

    def apply(self, row: RowPlan, *, by: User, cache: dict[str, Any]) -> None:
        amount = row.data["amount"]
        ledger.post_adjustment(
            row.data["retailer_id"],
            "OPENING_DEBIT" if amount > 0 else "OPENING_CREDIT",
            abs(amount),
            on=row.data["bill_date"],
            narration=row.data["note"],
            by=by,
            due_date=row.data["due_date"],
            bill_number=row.data["bill_number"],
        )

    def export_rows(self) -> Iterable[dict[str, str]]:
        return []
