"""Opening balances import (PLAN task 5.5, ADR-046): what each shop owed (or had paid in advance)
when the distributor started using the platform. One row per shop, matched by mobile number or
shop code; each becomes the shop's opening balance in its account (once per shop, audited)."""

from collections.abc import Iterable
from datetime import date
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError

from apps.accounts.models import User
from apps.dataio.kinds.base import Column, RowPlan
from apps.dataio.parsing import Sheet, parse_date, parse_decimal
from apps.ledger import services as ledger
from apps.ledger.models import EntryType, LedgerEntry
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.phone import normalize_indian_mobile

C = Column
COLUMNS: tuple[Column, ...] = (
    C(
        "shop",
        "Shop",
        ("mobile", "mobile number", "shop code", "retailer", "customer"),
        True,
        "The shop's mobile number or code (R-00001).",
        "9876500001",
    ),
    C(
        "amount",
        "Amount owed",
        ("balance", "opening balance", "outstanding", "due", "amount"),
        True,
        "What the shop owes you. Use a minus sign for money the shop paid in advance.",
        "12500.00",
    ),
    C(
        "as_of",
        "As of date",
        ("date", "balance date"),
        False,
        "The date of the balance (DD-MM-YYYY). Today if empty.",
        "31-03-2026",
    ),
    C(
        "note",
        "Note",
        ("narration", "remarks", "description"),
        False,
        "Shown on the shop's statement.",
        "Balance from old books",
    ),
)
LABEL = {c.name: c.label for c in COLUMNS}


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
        already = set(
            LedgerEntry.objects.filter(entry_type=EntryType.OPENING_BALANCE).values_list(
                "retailer_id", flat=True
            )
        )
        seen: dict[UUID, int] = {}
        plans: list[RowPlan] = []
        for row in sheet.rows:
            v = row.values
            plan = RowPlan(number=row.number, key=v.get("shop", ""))
            plans.append(plan)
            shop = _find(v["shop"], by_mobile, by_code) if v.get("shop") else None
            if not v.get("shop"):
                plan.error(LABEL["shop"], "Enter the shop's mobile number or code.")
            elif shop is None:
                plan.error(LABEL["shop"], f"No shop has the mobile number or code {v['shop']}.")
            amount = None
            try:
                amount = parse_decimal(v.get("amount", ""), places=2)
                if amount == 0:
                    plan.action = "UNCHANGED"
            except ValueError:
                plan.error(LABEL["amount"], "Enter the amount in rupees and paise, e.g. 12500.00.")
            as_of = today_ist()
            if v.get("as_of"):
                try:
                    as_of = parse_date(v["as_of"])
                except ValueError:
                    plan.error(LABEL["as_of"], "Use a date like 31-03-2026.")
                if as_of > today_ist():
                    plan.error(LABEL["as_of"], "The date can't be in the future.")
            if shop is None or amount is None or not plan.ok or plan.action == "UNCHANGED":
                continue
            plan.key = shop.code
            if shop.pk in already:
                plan.error(LABEL["shop"], "This shop already has an opening balance.")
                continue
            if shop.pk in seen:
                plan.error(LABEL["shop"], f"This shop is also in row {seen[shop.pk]}.")
                continue
            seen[shop.pk] = row.number
            plan.action = "NEW"
            plan.target_id = shop.pk
            plan.changes = {"Opening balance": ["", f"{amount:.2f}"]}
            plan.data = {
                "retailer_id": shop.pk,
                "amount": amount,
                "as_of": as_of,
                "note": v.get("note", "").strip() or "Opening balance (import)",
            }
        return plans

    def apply(self, row: RowPlan, *, by: User, cache: dict[str, Any]) -> None:
        amount = row.data["amount"]
        as_of: date = row.data["as_of"]
        ledger.post_adjustment(
            row.data["retailer_id"],
            "OPENING_DEBIT" if amount > 0 else "OPENING_CREDIT",
            abs(amount),
            on=as_of,
            narration=row.data["note"],
            by=by,
        )

    def export_rows(self) -> Iterable[dict[str, str]]:
        return []
