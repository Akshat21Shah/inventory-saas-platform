"""Pricing imports and exports (ADR-037 item 6): special prices, price-list prices and discount
rules, with the framework's explicit mode, change preview and row-level errors (ADR-035).

Shops are matched by mobile number or shop code, products by product code, price lists by name.
A discount rule is identified by its name; rows with the same name are one rule, one row per
quantity slab.
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models.functions import Lower
from django.utils.translation import gettext, gettext_lazy

from apps.accounts.models import User
from apps.catalog import selectors as catalog
from apps.catalog.models import Brand, Category, Product
from apps.dataio.kinds.base import Column, RowPlan
from apps.dataio.parsing import Sheet, parse_bool, parse_date, parse_decimal
from apps.pricing import services as pricing
from apps.pricing.models import DiscountRule, PriceList, PriceListItem, RetailerPrice
from apps.retailers.models import Retailer
from common.numbers import fill
from common.phone import normalize_indian_mobile

C = Column


def _free_note(for_list: bool) -> str:
    if for_list:
        return gettext(
            "A price of 0 makes this product free for the list's shops. Free-goods schemes are "
            "not supported yet."
        )
    return gettext(
        "A price of 0 makes this product free for this shop. Free-goods schemes are not "
        "supported yet."
    )


def _money(value: Decimal | None) -> str:
    return "" if value is None else f"{value:.2f}"


class _Lookups:
    """Shops, products and price lists for one file, loaded once."""

    def __init__(self, sheet: Sheet, *, shops: bool = False, lists: bool = False) -> None:
        codes = {r.values.get("product_code", "").strip().lower() for r in sheet.rows} - {""}
        self.products = {
            p.code.lower(): p
            for p in catalog.products().annotate(lc=Lower("code")).filter(lc__in=codes)
        }
        self.shops_by_mobile: dict[str, Retailer] = {}
        self.shops_by_code: dict[str, Retailer] = {}
        if shops:
            for shop in Retailer.objects.filter(deleted_at__isnull=True):
                self.shops_by_mobile[shop.mobile] = shop
                self.shops_by_code[shop.code.lower()] = shop
        self.lists = (
            {pl.name.lower(): pl for pl in PriceList.objects.filter(deleted_at__isnull=True)}
            if lists
            else {}
        )

    def shop(self, text: str) -> Retailer | None:
        text = text.strip()
        found = self.shops_by_code.get(text.lower())
        if found is not None:
            return found
        try:
            return self.shops_by_mobile.get(normalize_indian_mobile(text))
        except ValidationError:
            return None

    def product(self, text: str) -> Product | None:
        return self.products.get(text.strip().lower())


def _price(plan: RowPlan, label: str, text: str) -> Decimal | None:
    if not text:
        plan.error(label, gettext("Enter a price."))
        return None
    try:
        value = parse_decimal(text, places=2)
    except ValueError:
        plan.error(
            label,
            fill(
                gettext("%(text)s isn't an amount (use at most 2 decimal places)."), {"text": text}
            ),
        )
        return None
    if value < 0:
        plan.error(label, gettext("Can't be negative."))
        return None
    return value


# --- Special prices ------------------------------------------------------------------------------

SP_COLUMNS: tuple[Column, ...] = (
    C(
        "shop",
        "Shop",
        ("shop code", "retailer", "mobile", "shop mobile", "customer"),
        True,
        gettext_lazy("The shop's mobile number or code (R-00001)."),
        "9876543210",
    ),
    C("product_code", "Product code", ("code", "item code", "sku"), True, "", "PG-100"),
    C(
        "price",
        "Special price",
        ("price", "rate", "special rate"),
        True,
        gettext_lazy("The price this shop pays for one unit."),
        "8.75",
    ),
    C(
        "note",
        "Note",
        ("remarks", "comment"),
        False,
        gettext_lazy("Only your staff see it."),
        "Diwali deal",
    ),
    C(
        "shop_name",
        "Shop name",
        (),
        False,
        gettext_lazy("For reference; not imported."),
        "Ganesh Kirana",
    ),
    C(
        "product_name",
        "Product name",
        (),
        False,
        gettext_lazy("For reference; not imported."),
        "Parle-G 100g",
    ),
)
SP_LABEL = {c.name: c.label for c in SP_COLUMNS}


class SpecialPricesKind:
    code = "SPECIAL_PRICES"
    label = "Special prices"
    permission = "pricing.manage"
    key_label = SP_LABEL["product_code"]
    columns = SP_COLUMNS
    restricted: dict[str, str] = {}

    def reference_lists(self) -> dict[str, list[str]]:
        return {}

    def plan(self, sheet: Sheet, mode: str, by: User) -> list[RowPlan]:
        look = _Lookups(sheet, shops=True)
        existing = {(row.retailer_id, row.product_id): row for row in RetailerPrice.objects.all()}
        seen: dict[tuple[UUID, UUID], int] = {}
        plans: list[RowPlan] = []
        for row in sheet.rows:
            v = row.values
            plan = RowPlan(
                number=row.number, key=f"{v.get('shop', '')} / {v.get('product_code', '')}"
            )
            plans.append(plan)
            shop = look.shop(v.get("shop", "")) if v.get("shop") else None
            product = look.product(v.get("product_code", "")) if v.get("product_code") else None
            if not v.get("shop"):
                plan.error(SP_LABEL["shop"], gettext("Enter the shop's mobile number or code."))
            elif shop is None:
                plan.error(
                    SP_LABEL["shop"],
                    fill(
                        gettext("No shop has the mobile number or code %(shop)s."),
                        {"shop": v["shop"]},
                    ),
                )
            if not v.get("product_code"):
                plan.error(SP_LABEL["product_code"], gettext("Enter the product code."))
            elif product is None:
                plan.error(
                    SP_LABEL["product_code"],
                    fill(
                        gettext("No product has the code %(product_code)s."),
                        {"product_code": v["product_code"]},
                    ),
                )
            price = _price(plan, SP_LABEL["price"], v.get("price", ""))
            if shop is None or product is None or price is None:
                continue
            pair = (shop.pk, product.pk)
            if pair in seen:
                plan.error(
                    SP_LABEL["product_code"],
                    fill(
                        gettext(
                            "This shop and product are also in row %(value)s. List each pair once."
                        ),
                        {"value": seen[pair]},
                    ),
                )
                continue
            seen[pair] = row.number
            plan.key = f"{shop.code} / {product.code}"
            note = v.get("note", "")[:200]
            current = existing.get(pair)
            if price == 0:
                plan.warnings.append(_free_note(for_list=False))
            if current is None:
                plan.data = {
                    "retailer_id": shop.pk,
                    "product_id": product.pk,
                    "price": price,
                    "note": note,
                }
                continue
            if mode == "ADD_ONLY":
                plan.error(
                    SP_LABEL["product_code"],
                    fill(
                        gettext(
                            "%(code)s already has a special price for %(code2)s. To change it, "
                            "choose “Add new and update existing”."
                        ),
                        {"code": shop.code, "code2": product.code},
                    ),
                )
                continue
            plan.target_id = current.pk
            changes: dict[str, list[Any]] = {}
            if current.price != price:
                changes[SP_LABEL["price"]] = [_money(current.price), _money(price)]
            if "note" in sheet.columns and v.get("note") and current.note != note:
                changes[SP_LABEL["note"]] = [current.note, note]
            if not changes:
                plan.action = "UNCHANGED"
                continue
            plan.action, plan.changes = "UPDATE", changes
            plan.highlight = [SP_LABEL["price"]] if SP_LABEL["price"] in changes else []
            plan.data = {"price": price, "note": note if v.get("note") else current.note}
        return plans

    def apply(self, row: RowPlan, *, by: User, cache: dict[str, Any]) -> None:
        if row.target_id is None:
            pricing.save_retailer_price(None, by=by, **row.data)
        else:
            pricing.save_retailer_price(row.target_id, by=by, **row.data)

    def export_rows(self) -> Iterable[dict[str, str]]:
        rows = RetailerPrice.objects.select_related("retailer", "product").order_by(
            "retailer__code", "product__code"
        )
        for r in rows:
            yield {
                "shop": r.retailer.code,
                "product_code": r.product.code,
                "price": _money(r.price),
                "note": r.note,
                "shop_name": r.retailer.shop_name,
                "product_name": r.product.name,
            }


# --- Price-list prices ---------------------------------------------------------------------------

PL_COLUMNS: tuple[Column, ...] = (
    C(
        "price_list",
        "Price list",
        ("list", "price list name", "rate list"),
        True,
        gettext_lazy("The name of one of your price lists."),
        "Gold retailers",
    ),
    C("product_code", "Product code", ("code", "item code", "sku"), True, "", "PG-100"),
    C(
        "price",
        "Price",
        ("list price", "rate"),
        True,
        gettext_lazy("The list price for one unit."),
        "9.50",
    ),
    C(
        "product_name",
        "Product name",
        (),
        False,
        gettext_lazy("For reference; not imported."),
        "Parle-G 100g",
    ),
)
PL_LABEL = {c.name: c.label for c in PL_COLUMNS}


class PriceListItemsKind:
    code = "PRICE_LIST_ITEMS"
    label = "Price-list prices"
    permission = "pricing.manage"
    key_label = PL_LABEL["product_code"]
    columns = PL_COLUMNS
    restricted: dict[str, str] = {}

    def reference_lists(self) -> dict[str, list[str]]:
        return {
            "Price lists": sorted(
                PriceList.objects.filter(deleted_at__isnull=True).values_list("name", flat=True)
            )
        }

    def plan(self, sheet: Sheet, mode: str, by: User) -> list[RowPlan]:
        look = _Lookups(sheet, lists=True)
        existing = {(i.price_list_id, i.product_id): i for i in PriceListItem.objects.all()}
        seen: dict[tuple[UUID, UUID], int] = {}
        plans: list[RowPlan] = []
        for row in sheet.rows:
            v = row.values
            plan = RowPlan(
                number=row.number,
                key=f"{v.get('price_list', '')} / {v.get('product_code', '')}",
            )
            plans.append(plan)
            price_list = look.lists.get(v.get("price_list", "").strip().lower())
            product = look.product(v.get("product_code", "")) if v.get("product_code") else None
            if not v.get("price_list"):
                plan.error(PL_LABEL["price_list"], gettext("Enter the price list's name."))
            elif price_list is None:
                names = ", ".join(sorted(pl.name for pl in look.lists.values())[:10]) or "none yet"
                plan.error(
                    PL_LABEL["price_list"],
                    fill(
                        gettext(
                            "No price list is called %(price_list)s. Your price lists: %(names)s."
                        ),
                        {"price_list": v["price_list"], "names": names},
                    ),
                )
            if not v.get("product_code"):
                plan.error(PL_LABEL["product_code"], gettext("Enter the product code."))
            elif product is None:
                plan.error(
                    PL_LABEL["product_code"],
                    fill(
                        gettext("No product has the code %(product_code)s."),
                        {"product_code": v["product_code"]},
                    ),
                )
            price = _price(plan, PL_LABEL["price"], v.get("price", ""))
            if price_list is None or product is None or price is None:
                continue
            pair = (price_list.pk, product.pk)
            if pair in seen:
                plan.error(
                    PL_LABEL["product_code"],
                    fill(
                        gettext(
                            "This list and product are also in row %(value)s. List each pair once."
                        ),
                        {"value": seen[pair]},
                    ),
                )
                continue
            seen[pair] = row.number
            plan.key = f"{price_list.name} / {product.code}"
            if price == 0:
                plan.warnings.append(_free_note(for_list=True))
            plan.data = {"price_list_id": price_list.pk, "product_id": product.pk, "price": price}
            current = existing.get(pair)
            if current is None:
                continue
            if mode == "ADD_ONLY":
                plan.error(
                    PL_LABEL["product_code"],
                    fill(
                        gettext(
                            "%(name)s already has a price for %(code)s. To change it, choose “Add "
                            "new and update existing”."
                        ),
                        {"name": price_list.name, "code": product.code},
                    ),
                )
                continue
            plan.target_id = current.pk
            if current.price == price:
                plan.action = "UNCHANGED"
                continue
            plan.action = "UPDATE"
            plan.changes = {PL_LABEL["price"]: [_money(current.price), _money(price)]}
            plan.highlight = [PL_LABEL["price"]]
        return plans

    def apply(self, row: RowPlan, *, by: User, cache: dict[str, Any]) -> None:
        pricing.upsert_items(
            row.data["price_list_id"],
            [pricing.ItemInput(row.data["product_id"], row.data["price"])],
            by=by,
        )

    def export_rows(self) -> Iterable[dict[str, str]]:
        items = (
            PriceListItem.objects.filter(price_list__deleted_at__isnull=True)
            .select_related("price_list", "product")
            .order_by("price_list__name", "product__code")
        )
        for i in items:
            yield {
                "price_list": i.price_list.name,
                "product_code": i.product.code,
                "price": _money(i.price),
                "product_name": i.product.name,
            }


# --- Discount rules ------------------------------------------------------------------------------

DR_COLUMNS: tuple[Column, ...] = (
    C(
        "name",
        "Rule name",
        ("name", "discount name", "scheme"),
        True,
        gettext_lazy(
            "Identifies the rule. Rows with the same name are one rule, one row per slab."
        ),
        "Biscuits bulk",
    ),
    C(
        "product_code",
        "Product code",
        ("product", "code", "sku"),
        False,
        gettext_lazy("Fill one of product code, brand or category, or none for all products."),
        "",
    ),
    C("brand", "Brand", ("make",), False, "", ""),
    C(
        "category",
        "Category",
        ("group",),
        False,
        gettext_lazy("Up to 3 levels, e.g. Food > Biscuits."),
        "Food > Biscuits",
    ),
    C(
        "price_list",
        "Price list",
        ("list",),
        False,
        gettext_lazy("Fill a price list or a shop, or neither for all shops."),
        "",
    ),
    C(
        "shop",
        "Shop",
        ("shop code", "retailer", "mobile"),
        False,
        gettext_lazy("The shop's mobile number or code."),
        "",
    ),
    C(
        "type",
        "Type",
        ("discount type",),
        True,
        gettext_lazy("% or ₹ (rupees off each unit)."),
        "%",
    ),
    C(
        "value",
        "Discount",
        ("value", "discount value", "amount", "percent"),
        True,
        gettext_lazy("The percentage, or rupees off each unit. With a slab: the slab's discount."),
        "5",
    ),
    C(
        "slab",
        "From quantity",
        ("slab", "min qty", "minimum quantity", "quantity slab"),
        False,
        gettext_lazy("Optional quantity slab: the discount applies from this line quantity."),
        "24",
    ),
    C(
        "valid_from",
        "Valid from",
        ("from", "start date", "starts"),
        False,
        gettext_lazy("DD-MM-YYYY."),
        "",
    ),
    C("valid_to", "Valid to", ("to", "end date", "ends"), False, gettext_lazy("DD-MM-YYYY."), ""),
    C(
        "is_active",
        "Active",
        ("status", "enabled", "on"),
        False,
        gettext_lazy("Yes or No (default Yes)."),
        "Yes",
    ),
)
DR_LABEL = {c.name: c.label for c in DR_COLUMNS}
TYPES = {
    "%": "PERCENT",
    "percent": "PERCENT",
    "percentage": "PERCENT",
    "pct": "PERCENT",
    "₹": "FLAT_PER_UNIT",
    "rs": "FLAT_PER_UNIT",
    "rupees": "FLAT_PER_UNIT",
    "flat": "FLAT_PER_UNIT",
    "rupees off each unit": "FLAT_PER_UNIT",
    "per unit": "FLAT_PER_UNIT",
    "inr": "FLAT_PER_UNIT",
}
GROUP_FIELDS = (
    "product_code",
    "brand",
    "category",
    "price_list",
    "shop",
    "type",
    "valid_from",
    "valid_to",
    "is_active",
)


def _get(rule: DiscountRule | dict[str, Any], key: str) -> Any:
    return rule.get(key) if isinstance(rule, dict) else getattr(rule, key, None)


def _rule_summary(rule: DiscountRule | dict[str, Any], slabs: list[tuple[Decimal, Decimal]]) -> str:
    unit = "%" if _get(rule, "discount_type") == "PERCENT" else " ₹ each"
    if slabs:
        return "; ".join(f"{q.normalize():f}+: {v.normalize():f}{unit}" for q, v in slabs)
    return f"{Decimal(_get(rule, 'value')).normalize():f}{unit}"


class DiscountRulesKind:
    code = "DISCOUNT_RULES"
    label = "Discount rules"
    permission = "pricing.manage"
    key_label = DR_LABEL["name"]
    columns = DR_COLUMNS
    restricted: dict[str, str] = {}

    def reference_lists(self) -> dict[str, list[str]]:
        return {"Types": ["%", "₹"]}

    def _target(
        self, plan: RowPlan, v: dict[str, str], look: _Lookups, ref: dict[str, Any]
    ) -> dict[str, Any]:
        given = [k for k in ("product_code", "brand", "category") if v.get(k)]
        if len(given) > 1:
            plan.error(
                DR_LABEL[given[1]], gettext("Fill only one of product code, brand or category.")
            )
            return {}
        if not given:
            return {"scope_type": "ALL"}
        key = given[0]
        if key == "product_code":
            product = look.product(v[key])
            if product is None:
                plan.error(
                    DR_LABEL[key],
                    fill(gettext("No product has the code %(value)s."), {"value": v[key]}),
                )
                return {}
            return {"scope_type": "PRODUCT", "product_id": product.pk}
        if key == "brand":
            brand = ref["brands"].get(v[key].strip().lower())
            if brand is None:
                plan.error(
                    DR_LABEL[key], fill(gettext("No brand is called %(value)s."), {"value": v[key]})
                )
                return {}
            return {"scope_type": "BRAND", "brand_id": brand.pk}
        parent: UUID | None = None
        for part in [p.strip() for p in v[key].replace("»", ">").split(">") if p.strip()]:
            found = ref["categories"].get((parent, part.lower()))
            if found is None:
                plan.error(
                    DR_LABEL[key],
                    fill(
                        gettext("No category %(value)s (write it as Food > Biscuits)."),
                        {"value": v[key]},
                    ),
                )
                return {}
            parent = found.pk
        return {"scope_type": "CATEGORY", "category_id": parent}

    def _audience(self, plan: RowPlan, v: dict[str, str], look: _Lookups) -> dict[str, Any]:
        if v.get("price_list") and v.get("shop"):
            plan.error(DR_LABEL["shop"], gettext("Fill a price list or a shop, not both."))
            return {}
        if v.get("price_list"):
            price_list = look.lists.get(v["price_list"].strip().lower())
            if price_list is None:
                plan.error(
                    DR_LABEL["price_list"],
                    fill(
                        gettext("No price list is called %(price_list)s."),
                        {"price_list": v["price_list"]},
                    ),
                )
                return {}
            return {"audience_type": "PRICE_LIST", "price_list_id": price_list.pk}
        if v.get("shop"):
            shop = look.shop(v["shop"])
            if shop is None:
                plan.error(
                    DR_LABEL["shop"],
                    fill(
                        gettext("No shop has the mobile number or code %(shop)s."),
                        {"shop": v["shop"]},
                    ),
                )
                return {}
            return {"audience_type": "RETAILER", "retailer_id": shop.pk}
        return {"audience_type": "ALL"}

    def _row(
        self, plan: RowPlan, v: dict[str, str], look: _Lookups, ref: dict[str, Any]
    ) -> tuple[dict[str, Any], Decimal | None, Decimal | None]:
        data: dict[str, Any] = {"name": " ".join(v.get("name", "").split())}
        data.update(self._target(plan, v, look, ref))
        data.update(self._audience(plan, v, look))
        kind = TYPES.get(v.get("type", "").strip().lower())
        if kind is None:
            plan.error(
                DR_LABEL["type"], gettext("Write % (percentage) or ₹ (rupees off each unit).")
            )
        else:
            data["discount_type"] = kind
        value = slab = None
        try:
            value = parse_decimal(v.get("value", ""), places=2)
        except ValueError:
            plan.error(
                DR_LABEL["value"],
                fill(
                    gettext("%(value)s isn't a number."),
                    {"value": v.get("value") or gettext("An empty cell")},
                ),
            )
        if value is not None and kind is not None:
            errors: dict[str, list[str]] = {}
            pricing.check_value(kind, value, "value", errors)
            for message in errors.get("value", []):
                plan.error(DR_LABEL["value"], message)
        if v.get("slab"):
            try:
                slab = parse_decimal(v["slab"], places=3)
                if slab <= 0:
                    raise ValueError(v["slab"])
            except ValueError:
                plan.error(
                    DR_LABEL["slab"],
                    fill(gettext("%(slab)s isn't a quantity above 0."), {"slab": v["slab"]}),
                )
        for name in ("valid_from", "valid_to"):
            if v.get(name):
                try:
                    data[name] = parse_date(v[name])
                except ValueError:
                    plan.error(
                        DR_LABEL[name],
                        fill(
                            gettext("%(value)s isn't a date. Write DD-MM-YYYY."), {"value": v[name]}
                        ),
                    )
            else:
                data[name] = None
        if (
            data.get("valid_from")
            and data.get("valid_to")
            and data["valid_to"] < data["valid_from"]
        ):
            plan.error(
                DR_LABEL["valid_to"], gettext("The end date must be on or after the start date.")
            )
        try:
            data["is_active"] = parse_bool(v["is_active"]) if v.get("is_active") else True
        except ValueError:
            plan.error(
                DR_LABEL["is_active"],
                fill(
                    gettext("Write Yes or No (not “%(is_active)s”)."), {"is_active": v["is_active"]}
                ),
            )
        return data, value, slab

    def plan(self, sheet: Sheet, mode: str, by: User) -> list[RowPlan]:
        look = _Lookups(sheet, shops=True, lists=True)
        ref = {
            "brands": {b.name.lower(): b for b in Brand.objects.filter(deleted_at__isnull=True)},
            "categories": {
                (c.parent_id, c.name.lower()): c
                for c in Category.objects.filter(deleted_at__isnull=True)
            },
        }
        existing: dict[str, list[DiscountRule]] = defaultdict(list)
        for rule in DiscountRule.objects.prefetch_related("slabs"):
            existing[rule.name.lower()].append(rule)
        # Names for the change preview: everything a rule in the file or in the database can
        # point at (codes for products and shops).
        self._names: dict[Any, str] = {
            **{p.pk: p.code for p in Product.objects.all().only("pk", "code")},
            **{b.pk: b.name for b in Brand.objects.all().only("pk", "name")},
            **{c.pk: c.name for c in Category.objects.all().only("pk", "name")},
            **{pl.pk: pl.name for pl in PriceList.objects.all().only("pk", "name")},
            **{r.pk: r.code for r in Retailer.objects.all().only("pk", "code")},
        }
        groups: dict[
            str,
            list[tuple[RowPlan, dict[str, Any], dict[str, str], Decimal | None, Decimal | None]],
        ] = defaultdict(list)
        plans: list[RowPlan] = []
        for row in sheet.rows:
            v = row.values
            plan = RowPlan(number=row.number, key=" ".join(v.get("name", "").split()))
            plans.append(plan)
            if not plan.key:
                plan.error(DR_LABEL["name"], gettext("Enter the rule's name."))
                continue
            data, value, slab = self._row(plan, v, look, ref)
            groups[plan.key.lower()].append((plan, data, v, value, slab))
        for name, rows in groups.items():
            self._plan_rule(name, rows, existing.get(name, []), mode)
        return plans

    def _plan_rule(
        self,
        name: str,
        rows: list[tuple[RowPlan, dict[str, Any], dict[str, str], Decimal | None, Decimal | None]],
        matches: list[DiscountRule],
        mode: str,
    ) -> None:
        first, data, v0, value, _ = rows[0]
        # Rows of one rule must agree on everything except the slab and its discount.
        for plan, _data, v, _value, _slab in rows[1:]:
            for field_name in GROUP_FIELDS:
                if v.get(field_name, "") != v0.get(field_name, ""):
                    plan.error(
                        DR_LABEL[field_name],
                        fill(
                            gettext("Rows of the rule “%(key)s” must match row %(number)s here."),
                            {"key": first.key, "number": first.number},
                        ),
                    )
        slabbed = [r for r in rows if r[4] is not None]
        if slabbed and len(slabbed) != len(rows):
            for plan, *_ in rows:
                if plan.ok:
                    plan.error(
                        DR_LABEL["slab"], gettext("Give every row of a rule with slabs a quantity.")
                    )
        quantities = [r[4] for r in slabbed]
        if len(set(quantities)) != len(quantities):
            for plan, *_ in slabbed:
                plan.error(
                    DR_LABEL["slab"], gettext("Each slab of a rule needs a different quantity.")
                )
        if len(matches) > 1 and mode == "ADD_OR_UPDATE":
            first.error(
                DR_LABEL["name"],
                fill(
                    gettext(
                        "%(count)s rules are called “%(key)s”. Rename them first so each name is "
                        "used once."
                    ),
                    {"count": len(matches), "key": first.key},
                ),
            )
        elif matches and mode == "ADD_ONLY":
            first.error(
                DR_LABEL["name"],
                fill(
                    gettext(
                        "A rule called “%(key)s” already exists. To change it, choose “Add new "
                        "and update existing”."
                    ),
                    {"key": first.key},
                ),
            )
        failed = next((p for p, *_ in rows if not p.ok), None)
        if failed is not None:
            for plan, *_ in rows:
                if plan.ok:
                    plan.error(
                        DR_LABEL["name"],
                        fill(
                            gettext(
                                "Row %(number)s of this rule has a problem; the rule is skipped."
                            ),
                            {"number": failed.number},
                        ),
                    )
            return
        slabs: list[tuple[Decimal, Decimal]] = sorted(
            (r[4], r[3]) for r in slabbed if r[4] is not None and r[3] is not None
        )
        data["value"] = Decimal("0") if slabs else value
        if data.get("discount_type") == "PERCENT" and any(
            v >= 100 for v in [value, *[s[1] for s in slabs]] if v is not None
        ):
            first.warnings.append(
                gettext(
                    "A 100% discount makes products free. Free-goods schemes are not supported yet."
                )
            )
        first.data = {"rule": data, "slabs": slabs}
        for plan, *_ in rows[1:]:
            plan.data = {"part_of": first.number}  # applied with the first row
        if not matches:
            return
        rule = matches[0]
        old_slabs = sorted((s.min_qty, s.value) for s in rule.slabs.all())
        before = self._display(rule, old_slabs, self._names)
        after = self._display(data, slabs, self._names)
        changes = {k: [before[k], after[k]] for k in after if before[k] != after[k]}
        for plan, *_ in rows:
            plan.target_id = rule.pk
            plan.action = "UPDATE" if changes else "UNCHANGED"
        if changes:
            first.changes = changes
            first.highlight = [k for k in ("Discount",) if k in changes]

    def _display(
        self, rule: DiscountRule | dict[str, Any], slabs: list[Any], names: dict[Any, str]
    ) -> dict[str, str]:
        def name(key: str) -> str:
            return names.get(_get(rule, key), "?")

        target = {
            "ALL": "All products",
            "PRODUCT": f"Product {name('product_id')}",
            "BRAND": f"Brand {name('brand_id')}",
            "CATEGORY": f"Category {name('category_id')}",
        }[str(_get(rule, "scope_type"))]
        audience = {
            "ALL": "All shops",
            "PRICE_LIST": f"Price list {name('price_list_id')}",
            "RETAILER": f"Shop {name('retailer_id')}",
        }[str(_get(rule, "audience_type"))]
        dates = [_get(rule, "valid_from"), _get(rule, "valid_to")]
        return {
            "Discount": _rule_summary(rule, slabs),
            "Applies to": target,
            "For": audience,
            "Dates": " to ".join(
                d.strftime("%d-%m-%Y") if isinstance(d, date) else "…" for d in dates
            ),
            "Active": "Yes" if _get(rule, "is_active") else "No",
        }

    def apply(self, row: RowPlan, *, by: User, cache: dict[str, Any]) -> None:
        if "part_of" in row.data:
            return  # applied with the rule's first row
        data = dict(row.data["rule"])
        for key in ("product_id", "category_id", "brand_id", "price_list_id", "retailer_id"):
            data.setdefault(key, None)
        slabs = [pricing.SlabInput(q, v) for q, v in row.data["slabs"]]
        pricing.save_discount_rule(row.target_id, data, slabs, by=by)

    def export_rows(self) -> Iterable[dict[str, str]]:
        rules = (
            DiscountRule.objects.select_related(
                "product", "brand", "category__parent__parent", "price_list", "retailer"
            )
            .prefetch_related("slabs")
            .order_by("name", "created_at")
        )
        for rule in rules:
            category = ""
            if rule.category is not None:
                chain, node = [], rule.category
                while node is not None:
                    chain.append(node.name)
                    node = node.parent
                category = " > ".join(reversed(chain))
            base = {
                "name": rule.name,
                "product_code": rule.product.code if rule.product else "",
                "brand": rule.brand.name if rule.brand else "",
                "category": category,
                "price_list": rule.price_list.name if rule.price_list else "",
                "shop": rule.retailer.code if rule.retailer else "",
                "type": "%" if rule.discount_type == "PERCENT" else "₹",
                "valid_from": rule.valid_from.strftime("%d-%m-%Y") if rule.valid_from else "",
                "valid_to": rule.valid_to.strftime("%d-%m-%Y") if rule.valid_to else "",
                "is_active": "Yes" if rule.is_active else "No",
            }
            slabs = sorted(rule.slabs.all(), key=lambda s: s.min_qty)
            if not slabs:
                yield {**base, "value": f"{rule.value.normalize():f}", "slab": ""}
            for slab in slabs:
                yield {
                    **base,
                    "value": f"{slab.value.normalize():f}",
                    "slab": f"{slab.min_qty.normalize():f}",
                }
