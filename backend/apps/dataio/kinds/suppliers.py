"""Supplier import and export (ADR-053 item 4, flag ``purchasing``). A row matches an existing
supplier by GSTIN when it has one, otherwise by name (ignoring case and spacing)."""

import re
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.models import User
from apps.dataio.kinds.base import Column, RowPlan
from apps.dataio.parsing import Sheet, parse_decimal
from apps.platform.gst import gstin_problem
from apps.platform.models import State
from apps.platform.validators import normalize_gstin
from apps.purchasing import services
from apps.purchasing.models import Supplier
from apps.purchasing.selectors import name_key
from common.numbers import fill

C = Column
COLUMNS: tuple[Column, ...] = (
    C(
        "name",
        "Supplier name",
        ("supplier", "name", "party name", "vendor", "vendor name", "company"),
        True,
        "",
        "Hindustan Traders",
    ),
    C("gstin", "GSTIN", ("gst number", "gst no", "gstin uin"), False, "", "27AAGFK7315R1ZP"),
    C(
        "state",
        "State",
        ("state name", "state code"),
        False,
        gettext_lazy("Name or 2-digit GST code."),
        "",
    ),
    C("contact_name", "Contact person", ("contact", "contact name"), False, "", "Ravi Shah"),
    C("phone", "Phone", ("mobile", "phone number", "mobile number"), False, "", "9822012345"),
    C(
        "email",
        "Email",
        ("email id", "e-mail"),
        False,
        gettext_lazy("Purchase orders are sent here."),
        "",
    ),
    C("address_line1", "Address", ("address line 1", "street"), False, "", "Plot 4, MIDC"),
    C("address_line2", "Address line 2", ("area", "locality"), False, "", ""),
    C("city", "City", ("town",), False, "", "Pune"),
    C("pincode", "PIN code", ("pin", "pincode", "postal code"), False, "", "411019"),
    C(
        "payment_terms_days",
        "Payment days",
        ("credit days", "payment terms", "terms"),
        False,
        gettext_lazy("Days you have to pay them."),
        "30",
    ),
    C(
        "lead_time_days",
        "Delivery days",
        ("lead time", "lead time days", "delivery time"),
        False,
        gettext_lazy("Days from ordering to receiving. Empty = your usual delivery time."),
        "5",
    ),
    C("notes", "Notes", ("remarks", "comment"), False, "", ""),
)
LABEL = {c.name: c.label for c in COLUMNS}
TEXT = ("name", "contact_name", "phone", "email", "address_line1", "address_line2", "city")
FIELDS = (*TEXT, "gstin", "state_id", "pincode", "payment_terms_days", "lead_time_days", "notes")


class SuppliersKind:
    code = "SUPPLIERS"
    label = "Suppliers"
    permission = "purchasing.manage"
    feature = "purchasing"
    key_label = LABEL["name"]
    columns = COLUMNS
    restricted: dict[str, str] = {}

    def reference_lists(self) -> dict[str, list[str]]:
        return {"States": [f"{s.code} {s.name}" for s in State.objects.filter(is_active=True)]}

    def plan(self, sheet: Sheet, mode: str, by: User) -> list[RowPlan]:
        states = {s.code: s.code for s in State.objects.filter(is_active=True)}
        states |= {s.name.lower(): s.code for s in State.objects.filter(is_active=True)}
        current = list(Supplier.objects.filter(deleted_at__isnull=True))
        by_gstin = {s.gstin: s for s in current if s.gstin}
        by_name: dict[str, Supplier] = {}
        for supplier in current:
            by_name.setdefault(name_key(supplier.name), supplier)
        seen: dict[str, int] = {}
        plans: list[RowPlan] = []
        for row in sheet.rows:
            v = row.values
            plan = RowPlan(number=row.number, key=v.get("name", ""))
            plans.append(plan)
            data = self._parse(plan, v, states)
            # A supplier is the same by GSTIN or by name.
            keys = [k for k in (data.get("gstin"), name_key(v.get("name", ""))) if k]
            if not keys:
                plan.error(LABEL["name"], _("Enter the supplier's name."))
                continue
            twice = next((seen[k] for k in keys if k in seen), None)
            if twice is not None:
                plan.error(
                    LABEL["name"],
                    fill(_("Also in row %(twice)s. List each supplier once."), {"twice": twice}),
                )
                continue
            seen.update(dict.fromkeys(keys, row.number))
            existing = by_gstin.get(data["gstin"]) if data.get("gstin") else None
            existing = existing or by_name.get(name_key(v.get("name", "")))
            if existing is None:
                if not v.get("name"):
                    plan.error(LABEL["name"], _("Needed for a new supplier."))
                if plan.ok:
                    plan.action, plan.data = "NEW", data
            elif mode == "ADD_ONLY":
                plan.error(
                    LABEL["name"],
                    fill(
                        _(
                            "%(name)s is already a supplier. To change it, choose “Add new and "
                            "update existing”."
                        ),
                        {"name": existing.name},
                    ),
                )
            elif plan.ok:
                self._plan_update(plan, data, existing)
        return plans

    def _parse(self, plan: RowPlan, v: dict[str, str], states: dict[str, str]) -> dict[str, Any]:
        out: dict[str, Any] = {k: " ".join(v[k].split()) for k in TEXT if v.get(k)}
        if v.get("notes"):
            out["notes"] = v["notes"].strip()
        if out.get("email") and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", out["email"]):
            plan.error(
                LABEL["email"], fill(_("%(email)s isn't an email address."), {"email": v["email"]})
            )
        if out.get("phone") and not services.PHONE.fullmatch(out["phone"]):
            plan.error(LABEL["phone"], _("Enter a phone number with 10 to 15 digits."))
        if v.get("gstin"):
            gstin = normalize_gstin(v["gstin"])
            problem = gstin_problem(gstin)
            if problem:
                plan.error(LABEL["gstin"], problem)
            else:
                out["gstin"] = gstin
        if v.get("state"):
            raw = v["state"].strip()
            state = states.get(raw.zfill(2) if raw.isdigit() else raw.lower())
            if state is None:
                plan.error(
                    LABEL["state"],
                    fill(_("%(raw)s isn't a state. Use the name or the GST code."), {"raw": raw}),
                )
            elif out.get("gstin") and out["gstin"][:2] != state:
                plan.error(
                    LABEL["state"], _("The state must match the first 2 digits of the GSTIN.")
                )
            else:
                out["state_id"] = state
        if v.get("pincode"):
            if re.fullmatch(r"[1-9][0-9]{5}", v["pincode"].strip()):
                out["pincode"] = v["pincode"].strip()
            else:
                plan.error(
                    LABEL["pincode"],
                    fill(_("%(pincode)s isn't a 6-digit PIN code."), {"pincode": v["pincode"]}),
                )
        for name, low, high in (("payment_terms_days", 0, 365), ("lead_time_days", 1, 365)):
            if v.get(name):
                try:
                    days = parse_decimal(v[name], places=0)
                    if not Decimal(low) <= days <= Decimal(high):
                        raise ValueError
                    out[name] = int(days)
                except ValueError:
                    plan.error(
                        LABEL[name],
                        fill(_("Enter %(low)s to %(high)s days."), {"low": low, "high": high}),
                    )
        return out

    def _plan_update(self, plan: RowPlan, data: dict[str, Any], supplier: Supplier) -> None:
        if name_key(data.get("name", "")) == name_key(supplier.name):
            data.pop("name", None)  # the same name in other capitals or spacing: keep it
        changes: dict[str, list[Any]] = {}
        for name, value in data.items():
            old = getattr(supplier, name)
            if (old if old is not None else "") != value:
                label = LABEL.get(name.removesuffix("_id"), name)
                changes[label] = [old if old is not None else "", value]
        plan.target_id = supplier.pk
        if not changes:
            plan.action = "UNCHANGED"
            return
        plan.action, plan.changes, plan.data = "UPDATE", changes, data

    def apply(self, row: RowPlan, *, by: User, cache: dict[str, Any]) -> None:
        if row.target_id is None:
            services.create_supplier(dict(row.data), by=by)
        else:
            services.update_supplier(row.target_id, dict(row.data), by=by)

    def export_rows(self) -> Iterable[dict[str, str]]:
        for s in Supplier.objects.filter(deleted_at__isnull=True).order_by("code"):
            yield {
                "name": s.name,
                "gstin": s.gstin or "",
                "state": s.state_id or "",
                "contact_name": s.contact_name,
                "phone": s.phone,
                "email": s.email,
                "address_line1": s.address_line1,
                "address_line2": s.address_line2,
                "city": s.city,
                "pincode": s.pincode,
                "payment_terms_days": str(s.payment_terms_days),
                "lead_time_days": str(s.lead_time_days or ""),
                "notes": s.notes,
            }
