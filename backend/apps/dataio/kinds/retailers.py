"""Retailer import and export (spec 5.5, ADR-035). Shops are matched by mobile number; in an
update import the mobile number and the sign-in are never changed. New shops get their welcome
message when the import is committed."""

import re
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.functional import lazy
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.models import Membership, User
from apps.dataio.kinds.base import Column, RowPlan
from apps.dataio.parsing import Sheet, parse_decimal, split_list
from apps.platform.gst import gstin_problem
from apps.platform.models import State
from apps.platform.validators import normalize_gstin
from apps.pricing.models import PriceList
from apps.retailers import services
from apps.retailers.models import Retailer, RetailerAddress
from common.languages import all_languages
from common.phone import normalize_indian_mobile


def _language_names() -> str:
    """The language names for people, e.g. "English, Hindi or Marathi" (common/languages.json)."""
    names = [language.name for language in all_languages()]
    if len(names) == 1:
        return names[0]
    return _("%(names)s or %(last)s") % {"names": ", ".join(names[:-1]), "last": names[-1]}


def _language_help_now() -> str:
    return _("%(languages)s. Empty: your usual language for shops.") % {
        "languages": _language_names()
    }


_language_help = lazy(_language_help_now, str)  # in the language of whoever downloads it


C = Column
COLUMNS: tuple[Column, ...] = (
    C(
        "mobile",
        "Mobile",
        ("mobile number", "phone", "mobile no", "contact number", "whatsapp"),
        True,
        gettext_lazy("10-digit mobile number. The shop signs in with it."),
        "9876543210",
    ),
    C(
        "shop_name",
        "Shop name",
        ("shop", "name", "firm name", "retailer", "party name", "customer name"),
        True,
        "",
        "Ganesh Kirana Stores",
    ),
    C(
        "owner_name",
        "Owner name",
        ("owner", "contact person", "proprietor"),
        False,
        "",
        "Ganesh Patil",
    ),
    C("email", "Email", ("email id", "e-mail"), False, "", "ganesh@example.com"),
    C(
        "gstin",
        "GSTIN",
        ("gst number", "gst no", "gstin uin"),
        False,
        gettext_lazy("Leave empty for an unregistered shop."),
        "27AAGFK7315R1ZP",
    ),
    C(
        "state",
        "State",
        ("state name", "state code"),
        False,
        gettext_lazy("State name or 2-digit GST code. Needed when there is no GSTIN."),
        "Maharashtra",
    ),
    C(
        "address_line1",
        "Address",
        ("address line 1", "billing address", "street"),
        False,
        gettext_lazy("Billing address."),
        "12 Station Road",
    ),
    C("address_line2", "Address line 2", ("area", "locality"), False, "", "Near bus stand"),
    C("city", "City", ("town", "village"), False, "", "Pune"),
    C("district", "District", (), False, "", "Pune"),
    C("pincode", "PIN code", ("pin", "pincode", "postal code", "zip"), False, "", "411001"),
    C(
        "salesperson",
        "Salesperson email",
        ("salesperson", "sales person", "assigned to"),
        False,
        gettext_lazy("Email of a staff member."),
        "sales@yourfirm.com",
    ),
    C(
        "price_list",
        "Price list",
        ("price list name", "rate list"),
        False,
        gettext_lazy("Name of one of your price lists. Empty = your normal prices."),
        "Gold retailers",
    ),
    C(
        "credit_limit",
        "Credit limit",
        ("credit", "limit"),
        False,
        gettext_lazy("Empty = no limit, 0 = no credit. Needs the credit permission."),
        "50000",
    ),
    C(
        "payment_terms_days",
        "Payment days",
        ("credit days", "payment terms", "terms"),
        False,
        gettext_lazy("Days to pay. Needs the credit permission."),
        "30",
    ),
    C(
        "tags",
        "Tags",
        ("group", "category"),
        False,
        gettext_lazy("Separated by commas."),
        "wholesale",
    ),
    C(
        "preferred_language",
        "Language",
        ("lang",),
        False,
        _language_help(),
        "Marathi",
    ),
    C("notes", "Notes", ("remarks", "comment"), False, "", ""),
    C(
        "whatsapp_opt_in",
        "WhatsApp consent",
        ("whatsapp opt in", "agreed to whatsapp", "whatsapp messages"),
        False,
        gettext_lazy("Yes only if the shop agreed to get WhatsApp messages. No stops them."),
        "Yes",
    ),
)
YES = {"yes", "y", "true", "1", "haan", "ha"}
NO = {"no", "n", "false", "0", "nahi"}
LABEL = {c.name: c.label for c in COLUMNS}
ADDRESS = ("address_line1", "address_line2", "city", "district", "pincode")
CREDIT = ("credit_limit", "payment_terms_days")


def _languages() -> dict[str, str]:
    """Any language's code, English or native name → its code (from common/languages.json)."""
    from common.languages import by_any_name

    return by_any_name()


class RetailersKind:
    code = "RETAILERS"
    label = "Retailers"
    permission = "retailers.manage"
    key_label = LABEL["mobile"]
    columns = COLUMNS
    restricted: dict[str, str] = {}
    _emails: dict[Any, str]
    _lists: dict[Any, str]

    def reference_lists(self) -> dict[str, list[str]]:
        return {"States": [f"{s.code} {s.name}" for s in State.objects.filter(is_active=True)]}

    def plan(self, sheet: Sheet, mode: str, by: User) -> list[RowPlan]:
        states = {s.code: s.code for s in State.objects.filter(is_active=True)}
        states |= {s.name.lower(): s.code for s in State.objects.filter(is_active=True)}
        staff = {
            m.user.email.lower(): m.user.pk
            for m in Membership.objects.filter(is_active=True).select_related("user")
        }
        mobiles: dict[str, str] = {}
        for row in sheet.rows:
            try:
                mobiles[row.values.get("mobile", "")] = normalize_indian_mobile(
                    row.values.get("mobile", "")
                )
            except DjangoValidationError:
                continue
        existing = {
            r.mobile: r
            for r in Retailer.objects.filter(
                deleted_at__isnull=True, mobile__in=set(mobiles.values())
            )
            .select_related("salesperson")
            .prefetch_related("addresses")
        }
        self._emails = {user_id: email for email, user_id in staff.items()}
        lists = PriceList.objects.filter(deleted_at__isnull=True)
        self._lists = {p.pk: p.name for p in lists}
        price_lists = {p.name.lower(): p.pk for p in lists}
        can_credit = by.has_permission_code("credit.manage")
        ref = {"states": states, "staff": staff, "price_lists": price_lists}
        seen: dict[str, int] = {}
        plans: list[RowPlan] = []
        for row in sheet.rows:
            v = row.values
            plan = RowPlan(number=row.number, key=v.get("mobile", ""))
            plans.append(plan)
            mobile = mobiles.get(v.get("mobile", ""))
            if mobile is None:
                plan.error(
                    LABEL["mobile"],
                    _("Enter a 10-digit Indian mobile number.")
                    if v.get("mobile")
                    else _("Enter the shop's mobile number."),
                )
                continue
            if mobile in seen:
                plan.error(
                    LABEL["mobile"],
                    _("%(mobile)s is also in row %(value)s. List each shop only once.")
                    % {"mobile": v["mobile"], "value": seen[mobile]},
                )
                continue
            seen[mobile] = row.number
            if not can_credit and any(v.get(c) for c in CREDIT):
                plan.error(
                    LABEL["credit_limit"],
                    _(
                        "You can't set credit limits or payment days. "
                        "Remove these columns or ask someone with the credit permission."
                    ),
                )
            data = self._parse(plan, v, ref)
            retailer = existing.get(mobile)
            if retailer is None:
                self._plan_new(plan, v, data, mobile)
            elif mode == "ADD_ONLY":
                plan.error(
                    LABEL["mobile"],
                    _(
                        "A shop with mobile %(mobile)s already exists. To change it, choose “Add "
                        "new and update existing”."
                    )
                    % {"mobile": v["mobile"]},
                )
            else:
                self._plan_update(plan, data, retailer)
        return plans

    def _parse(self, plan: RowPlan, v: dict[str, str], ref: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in ("shop_name", "owner_name", "notes"):
            if v.get(name):
                out[name] = v[name]
        if v.get("email"):
            email = v["email"].strip().lower()
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                plan.error(
                    LABEL["email"], _("%(email)s isn't an email address.") % {"email": v["email"]}
                )
            else:
                out["email"] = email
        if v.get("gstin"):
            gstin = normalize_gstin(v["gstin"])
            problem = gstin_problem(gstin)
            if problem:
                plan.error(LABEL["gstin"], problem)
            else:
                out["gstin"] = gstin
        if v.get("state"):
            state = ref["states"].get(
                v["state"].strip().zfill(2)
                if v["state"].strip().isdigit()
                else v["state"].strip().lower()
            )
            if state is None:
                plan.error(
                    LABEL["state"],
                    _("%(state)s isn't a state. Use the name or the 2-digit GST code.")
                    % {"state": v["state"]},
                )
            else:
                out["state_id"] = state
        if "gstin" in out and out.get("state_id") and out["state_id"] != out["gstin"][:2]:
            plan.error(
                LABEL["state"],
                _("The state must match the first 2 digits of the GSTIN (%(value)s).")
                % {"value": out["gstin"][:2]},
            )
        if v.get("salesperson"):
            person = ref["staff"].get(v["salesperson"].strip().lower())
            if person is None:
                plan.error(
                    LABEL["salesperson"],
                    _("%(salesperson)s isn't an active staff member.")
                    % {"salesperson": v["salesperson"]},
                )
            else:
                out["salesperson_id"] = person
        if v.get("price_list"):
            found = ref["price_lists"].get(v["price_list"].strip().lower())
            if found is None:
                plan.error(
                    LABEL["price_list"],
                    _("%(price_list)s isn't one of your price lists.")
                    % {"price_list": v["price_list"]},
                )
            else:
                out["price_list_id"] = found
        if v.get("credit_limit"):
            try:
                limit = parse_decimal(v["credit_limit"], places=2)
                if limit < 0:
                    raise ValueError
                out["credit_limit"] = limit
            except ValueError:
                plan.error(
                    LABEL["credit_limit"],
                    _("%(credit_limit)s isn't an amount.") % {"credit_limit": v["credit_limit"]},
                )
        if v.get("payment_terms_days"):
            try:
                days = parse_decimal(v["payment_terms_days"], places=0)
                if not Decimal(0) <= days <= Decimal(365):
                    raise ValueError
                out["payment_terms_days"] = int(days)
            except ValueError:
                plan.error(LABEL["payment_terms_days"], _("Enter 0 to 365 days."))
        if v.get("tags"):
            out["tags"] = split_list(v["tags"])
        if v.get("preferred_language"):
            language = _languages().get(v["preferred_language"].strip().lower())
            if language is None:
                plan.error(
                    LABEL["preferred_language"],
                    _("Write %(languages)s.") % {"languages": _language_names()},
                )
            else:
                out["preferred_language"] = language
        if v.get("whatsapp_opt_in"):
            answer = v["whatsapp_opt_in"].strip().lower()
            if answer in YES | NO:
                out["whatsapp_opt_in"] = answer in YES
            else:
                plan.error(LABEL["whatsapp_opt_in"], _("Write Yes or No."))
        address = {k: v[k] for k in ADDRESS if v.get(k)}
        if address:
            out["address"] = address
        return out

    def _plan_new(
        self, plan: RowPlan, v: dict[str, str], data: dict[str, Any], mobile: str
    ) -> None:
        if not v.get("shop_name"):
            plan.error(LABEL["shop_name"], _("Needed for a new shop."))
        if not data.get("gstin") and not data.get("state_id") and not v.get("state"):
            plan.error(LABEL["state"], _("Needed when the shop has no GSTIN."))
        address = data.get("address", {})
        if address and not all(address.get(k) for k in ("address_line1", "city", "pincode")):
            plan.error(
                LABEL["address_line1"], _("For an address, fill in Address, City and PIN code.")
            )
        if address.get("pincode") and not re.fullmatch(r"[1-9][0-9]{5}", address["pincode"]):
            plan.error(
                LABEL["pincode"],
                _("%(pincode)s isn't a 6-digit PIN code.") % {"pincode": address["pincode"]},
            )
        if plan.ok:
            plan.action = "NEW"
            plan.data = {**data, "mobile": mobile}

    def _plan_update(self, plan: RowPlan, data: dict[str, Any], retailer: Retailer) -> None:
        if not plan.ok:
            return
        before = self._current(retailer)
        changes: dict[str, list[Any]] = {}
        for name, value in data.items():
            if name == "address":
                for key, new in value.items():
                    if before.get(key, "") != new:
                        changes[LABEL[key]] = [before.get(key, ""), new]
                continue
            key = name.removesuffix("_id")
            shown = (
                self._emails.get(value, "") if key == "salesperson" else self._display(name, value)
            )
            if before.get(key, "") != shown:
                changes[LABEL.get(key, key)] = [before.get(key, ""), shown]
        plan.target_id = retailer.pk
        if not changes:
            plan.action = "UNCHANGED"
            return
        plan.action, plan.changes, plan.data = "UPDATE", changes, data
        plan.highlight = [LABEL[c] for c in CREDIT if LABEL[c] in changes]

    def _current(self, r: Retailer) -> dict[str, str]:
        billing = next((a for a in r.addresses.all() if a.kind == "BILLING" and a.is_default), None)
        return {
            "shop_name": r.shop_name,
            "owner_name": r.owner_name,
            "email": r.email,
            "gstin": r.gstin or "",
            "state": r.state_id,
            "notes": r.notes,
            "salesperson": (r.salesperson.email or "") if r.salesperson else "",
            "price_list": r.price_list.name if r.price_list else "",
            "credit_limit": f"{r.credit_limit:.2f}" if r.credit_limit is not None else "",
            "payment_terms_days": str(r.payment_terms_days),
            "tags": ", ".join(r.tags),
            "preferred_language": r.preferred_language,
            "address_line1": billing.line1 if billing else "",
            "address_line2": billing.line2 if billing else "",
            "city": billing.city if billing else "",
            "district": billing.district if billing else "",
            "pincode": billing.pincode if billing else "",
            "whatsapp_opt_in": "Yes" if r.whatsapp_opt_in else "No",
        }

    def _display(self, name: str, value: Any) -> str:
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, Decimal):
            return f"{value:.2f}"
        if name == "tags":
            return ", ".join(services._clean_tags(value))
        return str(value)

    def apply(self, row: RowPlan, *, by: User, cache: dict[str, Any]) -> None:
        data = dict(row.data)
        address = data.pop("address", None)
        whatsapp = data.pop("whatsapp_opt_in", None)
        credit = {k: data.pop(k) for k in CREDIT if k in data}
        if row.target_id is None:
            retailer = services.create_retailer(
                shop_name=data.pop("shop_name"),
                phone=data.pop("mobile"),
                contact_name=data.pop("owner_name", ""),
                email=data.pop("email", ""),
                gstin=data.pop("gstin", None),
                state_id=data.pop("state_id", None),
                created_by=by,
                extra={**data, **credit},
            )
        else:
            if data:
                services.update_retailer(row.target_id, data, by=by)
            retailer = Retailer.objects.get(pk=row.target_id)
            if credit:
                services.update_credit(
                    retailer.pk,
                    credit_limit=credit.get("credit_limit", retailer.credit_limit),
                    payment_terms_days=credit.get(
                        "payment_terms_days", retailer.payment_terms_days
                    ),
                    by=by,
                )
        if address:
            self._save_billing(retailer, address, by)
        if whatsapp is not None:  # the distributor vouches for the shop's answer (ADR-048 item 5)
            from apps.notifications.consent import Source, set_whatsapp_consent

            set_whatsapp_consent(retailer.pk, whatsapp, source=Source.IMPORT, by=by)

    def _save_billing(self, retailer: Retailer, address: dict[str, str], by: User) -> None:
        """The default billing address, created or updated with the columns given."""
        billing = retailer.addresses.filter(kind="BILLING", is_default=True).first()
        names = {
            "address_line1": "line1",
            "address_line2": "line2",
            "city": "city",
            "district": "district",
            "pincode": "pincode",
        }
        fields: dict[str, Any] = {names[k]: value for k, value in address.items()}
        fields.setdefault("state_id", billing.state_id if billing else retailer.state_id)
        services.save_address(
            retailer.pk,
            billing.pk if billing else None,
            kind="BILLING",
            data=fields,
            is_default=True,
            by=by,
        )

    def export_rows(self) -> Iterable[dict[str, str]]:
        retailers = (
            Retailer.objects.filter(deleted_at__isnull=True)
            .select_related("salesperson", "price_list")
            .prefetch_related("addresses")
            .order_by("code")
        )
        names = {language.code: language.name for language in all_languages()}
        for r in retailers:
            billing = next(
                (
                    a
                    for a in r.addresses.all()
                    if a.kind == RetailerAddress.Kind.BILLING and a.is_default
                ),
                None,
            )
            yield {
                "mobile": r.mobile.removeprefix("+91"),
                "shop_name": r.shop_name,
                "owner_name": r.owner_name,
                "email": r.email,
                "gstin": r.gstin or "",
                "state": r.state_id,
                "address_line1": billing.line1 if billing else "",
                "address_line2": billing.line2 if billing else "",
                "city": billing.city if billing else "",
                "district": billing.district if billing else "",
                "pincode": billing.pincode if billing else "",
                "salesperson": (r.salesperson.email or "") if r.salesperson else "",
                "price_list": r.price_list.name if r.price_list else "",
                "credit_limit": f"{r.credit_limit:.2f}" if r.credit_limit is not None else "",
                "payment_terms_days": str(r.payment_terms_days),
                "tags": ", ".join(r.tags),
                "preferred_language": names.get(r.preferred_language, r.preferred_language),
                "notes": r.notes,
                "whatsapp_opt_in": "Yes" if r.whatsapp_opt_in else "No",
            }
