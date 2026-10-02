"""Product import and export (spec 5.4, ADR-035). Rows are checked with the same rules as the
product form; applying a row goes through the catalog services, so every change is audited
exactly like a manual one (price and MRP changes included)."""

import re
from collections.abc import Iterable
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models.functions import Lower
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.models import User
from apps.catalog import selectors, services
from apps.catalog.models import Category, Product, ProductBarcode, Unit
from apps.dataio.kinds.base import Column, RowPlan
from apps.dataio.parsing import Sheet, parse_bool, parse_decimal, split_list
from apps.platform.selectors import get_setting
from common.tenancy import require_tenant_id

C = Column
COLUMNS: tuple[Column, ...] = (
    C(
        "code",
        "Product code",
        ("code", "item code", "sku", "product id", "item no"),
        True,
        gettext_lazy("Your code for the product. Unique; used to find it again."),
        "PG-100",
    ),
    C(
        "name",
        "Product name",
        ("name", "item name", "product", "description of goods"),
        True,
        gettext_lazy("The name shops see."),
        "Parle-G Glucose Biscuits 100g",
    ),
    C(
        "unit",
        "Unit",
        ("uom", "unit of measure", "units"),
        True,
        gettext_lazy("The unit you sell in: a unit code from Catalog → Units (e.g. PCS, BOX, KG)."),
        "PCS",
    ),
    C(
        "hsn_code",
        "HSN code",
        ("hsn", "hsn sac", "hsn sac code", "hsn code no"),
        True,
        gettext_lazy("4 to 8 digits."),
        "1905",
    ),
    C(
        "gst_rate",
        "GST rate",
        ("gst", "gst %", "tax rate", "gst rate %", "igst rate"),
        True,
        gettext_lazy("The GST % in use today, e.g. 5 or 18."),
        "5",
    ),
    C(
        "base_price",
        "Price",
        ("base price", "selling price", "rate", "sale price", "price rs"),
        True,
        gettext_lazy("Your selling price per unit."),
        "9.00",
    ),
    C(
        "mrp",
        "MRP",
        ("maximum retail price", "mrp rs"),
        False,
        gettext_lazy("Printed MRP (includes GST)."),
        "10.00",
    ),
    C(
        "category",
        "Category",
        ("category path", "group", "product category"),
        False,
        gettext_lazy("Up to 3 levels, separated by >. Missing categories are created."),
        "Food > Biscuits",
    ),
    C(
        "brand",
        "Brand",
        ("brand name", "company", "make"),
        False,
        gettext_lazy("Missing brands are created."),
        "Parle",
    ),
    C(
        "min_order_qty",
        "Minimum order",
        ("min order qty", "moq", "minimum order qty"),
        False,
        gettext_lazy("Smallest quantity a shop can order (default 1)."),
        "1",
    ),
    C(
        "order_multiple",
        "Order in multiples of",
        ("order multiple", "multiple", "lot size"),
        False,
        gettext_lazy("Shops order in steps of this (default 1)."),
        "1",
    ),
    C(
        "pack_unit",
        "Pack unit",
        ("pack", "outer unit"),
        False,
        gettext_lazy("Optional bigger unit, e.g. BOX. Needs a pack size."),
        "BOX",
    ),
    C(
        "pack_size",
        "Pack size",
        ("units per pack", "pcs per box", "case size"),
        False,
        gettext_lazy("How many units are in one pack."),
        "12",
    ),
    C(
        "reorder_level",
        "Reorder level",
        ("reorder qty", "min stock"),
        False,
        gettext_lazy("Stock level that should trigger a reorder."),
        "50",
    ),
    C(
        "barcodes",
        "Barcodes",
        ("barcode", "ean", "upc"),
        False,
        gettext_lazy("One or more, separated by commas."),
        "8901719101038",
    ),
    C(
        "tags",
        "Tags",
        ("keywords",),
        False,
        gettext_lazy("Words that help search, separated by commas."),
        "glucose, tea time",
    ),
    C("description", "Description", ("details", "long description"), False, "", ""),
    C(
        "show_in_shop",
        "Show in shop",
        ("visible in shop", "shop visible"),
        False,
        gettext_lazy("Yes or No (default Yes)."),
        "Yes",
    ),
    C(
        "is_active",
        "Active",
        ("status", "enabled"),
        False,
        gettext_lazy("Yes or No (default Yes)."),
        "Yes",
    ),
    C(
        "cost_price",
        "Cost price",
        ("cost", "purchase price", "landing cost", "buying price"),
        False,
        gettext_lazy("What one unit costs you. Never shown to shops. Needs the cost permission."),
        "7.20",
    ),
)
LABEL = {c.name: c.label for c in COLUMNS}
REQUIRED = [c.name for c in COLUMNS if c.required]
PRICE_COLUMNS = ("base_price", "mrp", "cost_price")
CATEGORY_SPLIT = re.compile(r"\s*(?:>|»|/|\\)\s*")
MODEL_FIELD_TO_COLUMN = {
    "code": "code",
    "name": "name",
    "unit": "unit",
    "hsn_code": "hsn_code",
    "base_price": "base_price",
    "mrp": "mrp",
    "min_order_qty": "min_order_qty",
    "order_multiple": "order_multiple",
    "pack_unit": "pack_unit",
    "pack_size": "pack_size",
    "reorder_level": "reorder_level",
    "category": "category",
    "brand": "brand",
}


def _category_path(category: Category | None, by_id: dict[UUID, Category]) -> str:
    names: list[str] = []
    while category is not None:
        names.append(category.name)
        category = by_id.get(category.parent_id) if category.parent_id else None
    return " > ".join(reversed(names))


class ProductsKind:
    code = "PRODUCTS"
    label = "Products"
    permission = "products.manage"
    key_label = LABEL["code"]
    columns = COLUMNS
    restricted = {"cost_price": "costs.view"}  # ADR-042

    # --- reference data, loaded once per file --------------------------------------------------

    def _load(self) -> dict[str, Any]:
        categories = list(selectors.categories())
        return {
            "units": {u.code.upper(): u for u in selectors.units().filter(is_active=True)},
            "brands": {b.name.lower(): b for b in selectors.brands()},
            "categories": {(c.parent_id, c.name.lower()): c for c in categories},
            "categories_by_id": {c.pk: c for c in categories},
            "rates": services.active_rates(),
            "hsn_min": int(get_setting("tax.hsn_min_digits", require_tenant_id())),
        }

    def reference_lists(self) -> dict[str, list[str]]:
        ref = self._load()
        return {
            "GST rates in use": [f"{r.normalize():f}" for r in ref["rates"]],
            "Units": sorted(ref["units"]),
        }

    # --- validation ----------------------------------------------------------------------------

    def plan(self, sheet: Sheet, mode: str, by: User) -> list[RowPlan]:
        ref = self._load()
        codes = {r.values.get("code", "").strip().lower() for r in sheet.rows} - {""}
        matches = list(Product.objects.annotate(lc=Lower("code")).filter(lc__in=codes))
        existing = {p.code.lower(): p for p in matches if p.deleted_at is None}
        deleted_codes = {p.code.lower() for p in matches if p.deleted_at is not None}
        owners = dict(ProductBarcode.objects.values_list("barcode", "product_id"))
        rates = selectors.tax_rates_on([p.pk for p in existing.values()])
        can_cost = by.has_permission_code("costs.manage")
        seen_codes: dict[str, int] = {}
        seen_barcodes: dict[str, int] = {}
        plans: list[RowPlan] = []
        for row in sheet.rows:
            v = row.values
            key = v.get("code", "").strip()
            plan = RowPlan(number=row.number, key=key)
            plans.append(plan)
            if not key:
                plan.error(LABEL["code"], _("Enter the product code."))
                continue
            if len(key) > 40:
                plan.error(LABEL["code"], _("Use at most 40 characters."))
            lowered = key.lower()
            if lowered in seen_codes:
                plan.error(
                    LABEL["code"],
                    _("%(key)s is also in row %(value)s. List each product only once.")
                    % {"key": key, "value": seen_codes[lowered]},
                )
                continue
            seen_codes[lowered] = row.number
            product = existing.get(lowered)
            if product is None and lowered in deleted_codes:
                plan.error(
                    LABEL["code"],
                    _("%(key)s belonged to a deleted product. Use a new code.") % {"key": key},
                )
                continue
            if product is not None and mode == "ADD_ONLY":
                plan.error(
                    LABEL["code"],
                    _(
                        "A product with code %(key)s already exists. To change it, choose “Add "
                        "new and update existing”."
                    )
                    % {"key": key},
                )
                continue
            if v.get("cost_price") and not can_cost:
                plan.error(
                    LABEL["cost_price"],
                    _(
                        "You can't set cost prices. Remove this column or ask someone who "
                        "manages costs."
                    ),
                )
                continue
            if product is None:
                self._plan_new(plan, v, sheet.columns, ref)
            else:
                self._plan_update(plan, v, product, rates.get(product.pk), ref)
            self._check_barcodes(plan, v, owners, seen_barcodes, product)
        return plans

    def _parse_common(
        self, plan: RowPlan, v: dict[str, str], ref: dict[str, Any]
    ) -> dict[str, Any]:
        """Cells present and not blank → clean values (blank = "no change")."""
        out: dict[str, Any] = {}
        text_fields = ("name", "description")
        for name in text_fields:
            if v.get(name):
                out[name] = v[name]
        if v.get("unit"):
            unit = ref["units"].get(v["unit"].upper())
            if unit is None:
                plan.error(
                    LABEL["unit"],
                    f"{v['unit']} isn't one of your units ("
                    + ", ".join(sorted(ref["units"])[:15])
                    + ").",
                )
            else:
                out["unit"] = unit
        if v.get("pack_unit"):
            pack = ref["units"].get(v["pack_unit"].upper())
            if pack is None:
                plan.error(
                    LABEL["pack_unit"],
                    _("%(pack_unit)s isn't one of your units.") % {"pack_unit": v["pack_unit"]},
                )
            else:
                out["pack_unit"] = pack
        if v.get("hsn_code"):
            hsn = re.sub(r"[\s.]", "", v["hsn_code"])
            if hsn.isdigit() and len(hsn) % 2 == 1 and len(hsn) < 8:
                plan.warnings.append(
                    _("HSN %(hsn)s read as 0%(hsn)s (spreadsheets drop leading zeros).")
                    % {"hsn": hsn}
                )
                hsn = f"0{hsn}"
            if not hsn.isdigit() or not ref["hsn_min"] <= len(hsn) <= 8:
                plan.error(
                    LABEL["hsn_code"],
                    _("%(hsn_code)s isn't a valid HSN code. Use %(hsn_min)s to 8 digits.")
                    % {"hsn_code": v["hsn_code"], "hsn_min": ref["hsn_min"]},
                )
            else:
                out["hsn_code"] = hsn
        for name, places in (
            ("base_price", 2),
            ("mrp", 2),
            ("cost_price", 2),
            ("min_order_qty", 3),
            ("order_multiple", 3),
            ("pack_size", 3),
            ("reorder_level", 3),
        ):
            if v.get(name):
                try:
                    number = parse_decimal(v[name], places=places)
                except ValueError:
                    plan.error(
                        LABEL[name],
                        f"{v[name]} isn't a number"
                        + (" (use at most 2 decimal places)." if places == 2 else "."),
                    )
                    continue
                if number < 0:
                    plan.error(LABEL[name], _("Can't be negative."))
                    continue
                out[name] = number
        for name in ("show_in_shop", "is_active"):
            if v.get(name):
                try:
                    out[name] = parse_bool(v[name])
                except ValueError:
                    plan.error(
                        LABEL[name], _("Write Yes or No (not “%(value)s”).") % {"value": v[name]}
                    )
        if v.get("tags"):
            out["tags"] = split_list(v["tags"])
        if v.get("brand"):
            out["brand"] = v["brand"].strip()
        if v.get("category"):
            parts = [p for p in CATEGORY_SPLIT.split(v["category"]) if p]
            if len(parts) > 3:
                plan.error(LABEL["category"], _("Categories can be at most 3 levels deep."))
            else:
                out["category"] = parts
        return out

    def _gst(self, plan: RowPlan, text: str, ref: dict[str, Any]) -> Decimal | None:
        try:
            rate = parse_decimal(text, places=3)
        except ValueError:
            plan.error(
                LABEL["gst_rate"],
                _("%(text)s isn't a GST rate. Write a number such as 18.") % {"text": text},
            )
            return None
        if rate not in ref["rates"]:
            allowed = ", ".join(f"{r.normalize():f}" for r in ref["rates"])
            plan.error(
                LABEL["gst_rate"],
                _("%(rate)s%% isn't a GST rate in use. Use one of %(allowed)s.")
                % {"rate": format(rate.normalize(), "f"), "allowed": allowed},
            )
            return None
        return rate

    def _plan_new(
        self, plan: RowPlan, v: dict[str, str], columns: list[str], ref: dict[str, Any]
    ) -> None:
        for name in REQUIRED:
            if not v.get(name):
                plan.error(LABEL[name], _("Needed for a new product."))
        data = self._parse_common(plan, v, ref)
        data["code"] = plan.key
        if v.get("gst_rate"):
            data["gst_rate"] = self._gst(plan, v["gst_rate"], ref)
        if plan.problems:
            return
        product = self._unsaved(data, ref)
        self._rule_errors(plan, product)
        plan.data = data
        plan.warnings.extend(w.message for w in services.price_warnings(product, data["gst_rate"]))

    def _plan_update(
        self, plan: RowPlan, v: dict[str, str], product: Product, current: Any, ref: dict[str, Any]
    ) -> None:
        data = self._parse_common(plan, v, ref)
        if v.get("gst_rate"):
            rate = self._gst(plan, v["gst_rate"], ref)
            if rate is not None and (current is None or rate != current.gst_rate):
                plan.error(
                    LABEL["gst_rate"],
                    _(
                        "GST changes need a start date: schedule them under Products → GST "
                        "rates. The current rate is %(gst_rate)s%%."
                    )
                    % {"gst_rate": format(current.gst_rate.normalize(), "f")}
                    if current
                    else _(
                        "This product has no GST rate in effect; schedule one under "
                        "Products → GST rates."
                    ),
                )
        if plan.problems:
            return
        before = self._current(product, ref)
        after = dict(before)
        for name, value in data.items():
            after[name] = self._display(name, value)
        changes = {
            LABEL[k]: [before.get(k, ""), after[k]] for k in after if after[k] != before.get(k, "")
        }
        plan.target_id = product.pk
        if not changes:
            plan.action = "UNCHANGED"
            return
        plan.action = "UPDATE"
        plan.changes = changes
        plan.highlight = [LABEL[c] for c in PRICE_COLUMNS if LABEL[c] in changes]
        plan.data = data
        candidate = Product(
            **{f.attname: getattr(product, f.attname) for f in Product._meta.concrete_fields}
        )
        self._fill(candidate, data, ref)
        self._rule_errors(plan, candidate)
        rate = current.gst_rate if current else None
        plan.warnings.extend(w.message for w in services.price_warnings(candidate, rate))

    def _current(self, product: Product, ref: dict[str, Any]) -> dict[str, str]:
        units_by_id = {u.pk: u.code for u in ref["units"].values()}
        return {
            "name": product.name,
            "description": product.description,
            "unit": units_by_id.get(product.unit_id, ""),
            "pack_unit": units_by_id.get(product.pack_unit_id, "") if product.pack_unit_id else "",
            "hsn_code": product.hsn_code,
            "base_price": f"{product.base_price:.2f}",
            "mrp": f"{product.mrp:.2f}" if product.mrp is not None else "",
            "cost_price": f"{product.cost_price:.2f}" if product.cost_price is not None else "",
            "min_order_qty": f"{product.min_order_qty.normalize():f}",
            "order_multiple": f"{product.order_multiple.normalize():f}",
            "pack_size": f"{product.pack_size.normalize():f}"
            if product.pack_size is not None
            else "",
            "reorder_level": f"{product.reorder_level.normalize():f}",
            "tags": ", ".join(product.tags),
            "show_in_shop": "Yes" if product.show_in_shop else "No",
            "is_active": "Yes" if product.is_active else "No",
            "brand": product.brand.name if product.brand_id and product.brand else "",
            "category": _category_path(product.category, ref["categories_by_id"])
            if product.category_id
            else "",
        }

    def _display(self, name: str, value: Any) -> str:
        if isinstance(value, Unit):
            return value.code
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, Decimal):
            return f"{value:.2f}" if name in PRICE_COLUMNS else f"{value.normalize():f}"
        if name == "tags":
            return ", ".join(services._clean_tags(value))
        if name == "category":
            return " > ".join(value)
        return str(value)

    def _fill(self, product: Product, data: dict[str, Any], ref: dict[str, Any]) -> None:
        for name, value in data.items():
            if name in ("unit", "pack_unit"):
                setattr(product, f"{name}_id", value.pk)
            elif name in ("brand", "category", "gst_rate", "barcodes"):
                continue  # resolved (and created if missing) when applied
            else:
                setattr(product, name, value)

    def _unsaved(self, data: dict[str, Any], ref: dict[str, Any]) -> Product:
        product = Product(tenant_id=require_tenant_id())
        self._fill(product, data, ref)
        return product

    def _rule_errors(self, plan: RowPlan, product: Product) -> None:
        for field_name, messages in services.validate_product(product).items():
            if field_name in ("category", "brand"):
                continue
            label = LABEL.get(MODEL_FIELD_TO_COLUMN.get(field_name, field_name), field_name)
            for message in messages:
                plan.error(label, message)

    def _check_barcodes(
        self,
        plan: RowPlan,
        v: dict[str, str],
        owners: dict[str, UUID],
        seen: dict[str, int],
        product: Product | None,
    ) -> None:
        if not v.get("barcodes"):
            return
        codes = [re.sub(r"\s", "", b) for b in split_list(v["barcodes"])]
        for code in codes:
            if len(code) > 64:
                plan.error(
                    LABEL["barcodes"],
                    _("%(value)s… is longer than 64 characters.") % {"value": code[:20]},
                )
            elif code in seen and seen[code] != plan.number:
                plan.error(
                    LABEL["barcodes"],
                    _("%(code)s is also in row %(value)s.") % {"code": code, "value": seen[code]},
                )
            elif code in owners and (product is None or owners[code] != product.pk):
                plan.error(
                    LABEL["barcodes"],
                    _("%(code)s already belongs to another product.") % {"code": code},
                )
            seen.setdefault(code, plan.number)
        plan.data["barcodes"] = codes

    # --- applying ------------------------------------------------------------------------------

    def _brand(self, name: str, by: User, cache: dict[str, Any]) -> UUID:
        brands = cache.setdefault("brands", {b.name.lower(): b.pk for b in selectors.brands()})
        if name.lower() not in brands:
            brands[name.lower()] = services.save_brand(None, name=name, by=by).pk
        brand_id: UUID = brands[name.lower()]
        return brand_id

    def _category(self, parts: list[str], by: User, cache: dict[str, Any]) -> UUID:
        found = cache.setdefault(
            "categories", {(c.parent_id, c.name.lower()): c.pk for c in selectors.categories()}
        )
        parent: UUID | None = None
        for name in parts:
            key = (parent, name.lower())
            if key not in found:
                found[key] = services.create_category(name=name, parent_id=parent, by=by).pk
            parent = found[key]
        assert parent is not None
        return parent

    def apply(self, row: RowPlan, *, by: User, cache: dict[str, Any]) -> None:
        data = dict(row.data)
        barcodes = data.pop("barcodes", [])
        fields: dict[str, Any] = {}
        for name, value in data.items():
            if name in ("unit", "pack_unit"):
                fields[f"{name}_id"] = value.pk
            elif name == "brand":
                fields["brand_id"] = self._brand(value, by, cache)
            elif name == "category":
                fields["category_id"] = self._category(value, by, cache)
            elif name != "gst_rate":
                fields[name] = value
        if row.target_id is None:
            services.create_product(fields, gst_rate=data["gst_rate"], barcodes=barcodes, by=by)
            return
        if fields:
            services.update_product(row.target_id, fields, by=by)
        have = set(
            ProductBarcode.objects.filter(product_id=row.target_id).values_list(
                "barcode", flat=True
            )
        )
        for code in barcodes:
            if code not in have:
                services.add_barcode(row.target_id, code, by=by)

    # --- export (same columns as the template, so a file can go out and back in) -------------

    def export_rows(self) -> Iterable[dict[str, str]]:
        """Every column; ``build_export`` drops the ones the user may not see (cost price)."""
        by_id = {c.pk: c for c in selectors.categories(include_deleted=True)}
        products = list(selectors.products().prefetch_related("barcodes").order_by("code"))
        rates = selectors.tax_rates_on([p.pk for p in products])
        for p in products:
            rate = rates.get(p.pk)
            yield {
                "code": p.code,
                "name": p.name,
                "unit": p.unit.code,
                "hsn_code": p.hsn_code,
                "gst_rate": f"{rate.gst_rate.normalize():f}" if rate else "",
                "base_price": f"{p.base_price:.2f}",
                "mrp": f"{p.mrp:.2f}" if p.mrp is not None else "",
                "cost_price": f"{p.cost_price:.2f}" if p.cost_price is not None else "",
                "category": _category_path(p.category, by_id) if p.category_id else "",
                "brand": p.brand.name if p.brand else "",
                "min_order_qty": f"{p.min_order_qty.normalize():f}",
                "order_multiple": f"{p.order_multiple.normalize():f}",
                "pack_unit": p.pack_unit.code if p.pack_unit else "",
                "pack_size": f"{p.pack_size.normalize():f}" if p.pack_size is not None else "",
                "reorder_level": f"{p.reorder_level.normalize():f}",
                "barcodes": ", ".join(b.barcode for b in p.barcodes.all()),
                "tags": ", ".join(p.tags),
                "description": p.description,
                "show_in_shop": "Yes" if p.show_in_shop else "No",
                "is_active": "Yes" if p.is_active else "No",
            }
