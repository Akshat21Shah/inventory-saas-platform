"""Catalog writes (PLAN §2.4, spec 5.4). Every change is audited; price, MRP and GST changes are
the sensitive ones (CLAUDE.md §4)."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.text import slugify
from PIL import Image

from apps.accounts.models import User
from apps.audit import services as audit
from apps.catalog import selectors
from apps.catalog.models import (
    MAX_CATEGORY_DEPTH,
    Brand,
    Category,
    Product,
    ProductBarcode,
    ProductImage,
    ProductTaxRate,
    Unit,
)
from apps.inventory import alerts as inventory_alerts
from apps.inventory import services as inventory
from apps.platform.models import CessType, TaxRate
from apps.platform.selectors import get_setting
from common.dates import today_ist
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields, NotFound
from common.storage import get_storage
from common.tenancy import require_tenant_id, tenant_transaction
from common.uploads import validate_image

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile


class InUse(DomainError):
    status_code = 409
    code = ErrorCode.IN_USE
    default_message = "This is still in use, so it can't be deleted."


class CategoryTooDeep(DomainError):
    code = ErrorCode.CATEGORY_TOO_DEEP
    default_message = "Categories can be at most 3 levels deep."


class TaxRateNotCancellable(DomainError):
    status_code = 409
    code = ErrorCode.TAX_RATE_NOT_CANCELLABLE
    default_message = "Only a change that has not taken effect yet can be cancelled."


class PreviewOutOfDate(DomainError):
    status_code = 409
    code = ErrorCode.PREVIEW_OUT_OF_DATE
    default_message = "The products matching this change have changed. Preview it again."


@dataclass
class Warning:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


# --- Categories ---------------------------------------------------------------------------------


def _depth_below(category: Category) -> int:
    """Levels in the subtree under ``category`` (0 when it has no children)."""
    depth, frontier = 0, {category.pk}
    while True:
        frontier = set(
            Category.objects.filter(parent_id__in=frontier, deleted_at__isnull=True).values_list(
                "pk", flat=True
            )
        )
        if not frontier:
            return depth
        depth += 1


def _parent(parent_id: UUID | None) -> Category | None:
    if parent_id is None:
        return None
    parent = selectors.category(parent_id)
    if parent is None:
        raise InvalidFields({"parent": ["Choose an existing category."]})
    return parent


@transaction.atomic
def create_category(
    *, name: str, parent_id: UUID | None = None, sort_order: int = 0, by: User
) -> Category:
    name = name.strip()
    parent = _parent(parent_id)
    level = parent.level + 1 if parent else 1
    if level > MAX_CATEGORY_DEPTH:
        raise CategoryTooDeep()
    category = Category(
        name=name,
        slug=slugify(name)[:140] or "category",
        parent=parent,
        level=level,
        sort_order=sort_order,
        created_by=by,
    )
    try:
        with transaction.atomic():
            category.save()
    except IntegrityError as exc:
        raise InvalidFields({"name": ["A category with this name already exists here."]}) from exc
    audit.record("catalog.category_created", target=category, target_repr=name)
    return category


@transaction.atomic
def update_category(category_id: UUID, changes: dict[str, Any], *, by: User) -> Category:
    category = selectors.category(category_id)
    if category is None:
        raise NotFound()
    before = {
        "name": category.name,
        "parent": category.parent_id,
        "sort_order": category.sort_order,
    }
    if "name" in changes:
        category.name = changes["name"].strip()
        category.slug = slugify(category.name)[:140] or "category"
    if "sort_order" in changes:
        category.sort_order = changes["sort_order"]
    if "parent_id" in changes and changes["parent_id"] != category.parent_id:
        parent = _parent(changes["parent_id"])
        if parent is not None and parent.pk in selectors.descendant_ids(category.pk):
            raise InvalidFields({"parent": ["A category can't be moved under itself."]})
        level = parent.level + 1 if parent else 1
        if level + _depth_below(category) > MAX_CATEGORY_DEPTH:
            raise CategoryTooDeep()
        _move(category, parent, level)
    try:
        with transaction.atomic():
            category.save()
    except IntegrityError as exc:
        raise InvalidFields({"name": ["A category with this name already exists here."]}) from exc
    after = {"name": category.name, "parent": category.parent_id, "sort_order": category.sort_order}
    changes_made = audit.diff(before, after)
    if changes_made:
        audit.record(
            "catalog.category_updated",
            target=category,
            target_repr=category.name,
            changes=changes_made,
        )
    return category


def _move(category: Category, parent: Category | None, level: int) -> None:
    """Re-level the moved category and its subtree."""
    shift = level - category.level
    category.parent, category.level = parent, level
    if shift:
        ids = selectors.descendant_ids(category.pk) - {category.pk}
        for child in Category.objects.filter(pk__in=ids):
            child.level += shift
            child.save(update_fields=["level", "updated_at"])


@transaction.atomic
def delete_category(category_id: UUID, *, by: User) -> None:
    category = selectors.category(category_id)
    if category is None:
        raise NotFound()
    if Category.objects.filter(parent=category, deleted_at__isnull=True).exists():
        raise InUse("Move or delete its sub-categories first.")
    if Product.objects.filter(category=category, deleted_at__isnull=True).exists():
        raise InUse("Move its products to another category first.")
    category.deleted_at, category.is_active = timezone.now(), False
    category.save(update_fields=["deleted_at", "is_active", "updated_at"])
    audit.record("catalog.category_deleted", target=category, target_repr=category.name)


# --- Brands and units ---------------------------------------------------------------------------


@transaction.atomic
def save_brand(
    brand_id: UUID | None, *, name: str, own_brand: bool | None = None, by: User
) -> Brand:
    """``own_brand=None`` keeps the current value (ADR-039)."""
    name = name.strip()
    if brand_id is None:
        brand = Brand(name=name, own_brand=bool(own_brand), created_by=by)
        before = None
    else:
        found = selectors.brands().filter(pk=brand_id).first()
        if found is None:
            raise NotFound()
        brand, before = found, {"name": found.name, "own_brand": found.own_brand}
        brand.name = name
        if own_brand is not None:
            brand.own_brand = own_brand
    try:
        with transaction.atomic():
            brand.save()
    except IntegrityError as exc:
        raise InvalidFields({"name": ["A brand with this name already exists."]}) from exc
    if before is None:
        audit.record(
            "catalog.brand_created",
            target=brand,
            target_repr=name,
            changes={"own_brand": [None, brand.own_brand]} if brand.own_brand else {},
        )
    else:
        changes = audit.diff(before, {"name": brand.name, "own_brand": brand.own_brand})
        if changes:
            audit.record("catalog.brand_updated", target=brand, target_repr=name, changes=changes)
    return brand


@transaction.atomic
def delete_brand(brand_id: UUID, *, by: User) -> None:
    brand = selectors.brands().filter(pk=brand_id).first()
    if brand is None:
        raise NotFound()
    if Product.objects.filter(brand=brand, deleted_at__isnull=True).exists():
        raise InUse("Some products still use this brand.")
    brand.deleted_at, brand.is_active = timezone.now(), False
    brand.save(update_fields=["deleted_at", "is_active", "updated_at"])
    audit.record("catalog.brand_deleted", target=brand, target_repr=brand.name)


UNIT_FIELDS = ("code", "name", "allows_decimal", "uqc", "is_active")


@transaction.atomic
def save_unit(unit_id: UUID | None, changes: dict[str, Any], *, by: User) -> Unit:
    if unit_id is None:
        unit = Unit(created_by=by)
        before: dict[str, Any] = {}
    else:
        found = selectors.units().filter(pk=unit_id).first()
        if found is None:
            raise NotFound()
        unit = found
        before = {f: getattr(unit, f) for f in UNIT_FIELDS}
    for key in UNIT_FIELDS:
        if key in changes:
            value = changes[key]
            setattr(unit, key, value.strip().upper() if key in ("code", "uqc") else value)
    if unit.pk and before.get("allows_decimal") and not unit.allows_decimal:
        quantities = Product.objects.filter(unit=unit).values_list(
            "min_order_qty", "order_multiple"
        )
        if any(q != q.to_integral_value() for pair in quantities for q in pair):
            raise InvalidFields(
                {"allows_decimal": ["Some products using this unit have fractional quantities."]}
            )
    try:
        with transaction.atomic():
            unit.save()
    except IntegrityError as exc:
        raise InvalidFields({"code": ["A unit with this code already exists."]}) from exc
    after = {f: getattr(unit, f) for f in UNIT_FIELDS}
    audit.record(
        "catalog.unit_created" if not before else "catalog.unit_updated",
        target=unit,
        target_repr=unit.code,
        changes=audit.diff(before, after),
    )
    return unit


@transaction.atomic
def delete_unit(unit_id: UUID, *, by: User) -> None:
    unit = selectors.units().filter(pk=unit_id).first()
    if unit is None:
        raise NotFound()
    if (
        Product.objects.filter(unit=unit).exists()
        or Product.objects.filter(pack_unit=unit).exists()
    ):
        raise InUse("Some products use this unit. Mark it inactive instead.")
    code = unit.code
    unit.delete()
    audit.record(
        "catalog.unit_deleted", target_type="catalog.unit", target_id=unit_id, target_repr=code
    )


# --- Products -----------------------------------------------------------------------------------

PRODUCT_FIELDS = (
    "code",
    "name",
    "description",
    "category_id",
    "brand_id",
    "unit_id",
    "pack_unit_id",
    "pack_size",
    "hsn_code",
    "mrp",
    "base_price",
    "min_order_qty",
    "order_multiple",
    "reorder_level",
    "tags",
    "show_in_shop",
    "is_active",
    "cost_price",
)
PRICE_FIELDS = ("base_price", "mrp", "cost_price")
COST_PERMISSION = "pricing.manage"  # ADR-039: seen with pricing.view, set with pricing.manage


def _clean_tags(tags: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for tag in tags:
        tag = " ".join(str(tag).split()).lower()[:40]
        if tag and tag not in seen:
            seen.append(tag)
    return seen[:20]


def active_rates() -> list[Decimal]:
    rates = TaxRate.objects.filter(is_active=True).order_by("rate")
    return list(rates.values_list("rate", flat=True))


def _active_rate(value: Decimal) -> Decimal:
    rate = TaxRate.objects.filter(rate=value).first()
    if rate is None or not rate.is_active:
        allowed = ", ".join(
            f"{r.normalize():f}%"
            for r in TaxRate.objects.filter(is_active=True).values_list("rate", flat=True)
        )
        raise InvalidFields({"gst_rate": [f"Choose one of the GST rates in use: {allowed}."]})
    return value


def _cess(cess_type_id: UUID | None, cess_rate: Decimal) -> tuple[CessType | None, Decimal]:
    if cess_type_id is None:
        if cess_rate:
            raise InvalidFields({"cess_type": ["Choose the cess type for this cess rate."]})
        return None, Decimal("0")
    cess = CessType.objects.filter(pk=cess_type_id, is_active=True).first()
    if cess is None:
        raise InvalidFields({"cess_type": ["Choose an active cess type."]})
    if cess.calc_method != CessType.CalcMethod.PERCENT:
        raise InvalidFields({"cess_type": ["Only percentage cess is supported for now."]})
    if not Decimal("0") <= cess_rate <= Decimal("100"):
        raise InvalidFields({"cess_rate": ["Enter a cess rate from 0 to 100."]})
    return cess, cess_rate


def _normalize_numbers(product: Product) -> None:
    """Model defaults are plain ints; the rules below work on Decimals."""
    for name in (
        "min_order_qty",
        "order_multiple",
        "reorder_level",
        "pack_size",
        "mrp",
        "base_price",
        "cost_price",
    ):
        value = getattr(product, name)
        if value is not None and not isinstance(value, Decimal):
            setattr(product, name, Decimal(str(value)))


def validate_product(product: Product) -> dict[str, list[str]]:
    """The product rules, without saving (imports check every row before anything is saved)."""
    _normalize_numbers(product)
    errors: dict[str, list[str]] = {}
    _validate_product(product, errors)
    return errors


def _validate_product(product: Product, errors: dict[str, list[str]]) -> None:
    min_digits = int(get_setting("tax.hsn_min_digits", require_tenant_id()))
    hsn = product.hsn_code
    if not hsn.isdigit() or not min_digits <= len(hsn) <= 8:
        errors.setdefault("hsn_code", []).append(
            f"Enter an HSN code of {min_digits} to 8 digits (numbers only)."
        )
    for ref, qs, label in (
        ("category", selectors.categories(), "category"),
        ("brand", selectors.brands(), "brand"),
    ):
        ref_id = getattr(product, f"{ref}_id")
        if ref_id and not qs.filter(pk=ref_id).exists():
            errors.setdefault(ref, []).append(f"Choose an existing {label}.")
    unit = selectors.units().filter(pk=product.unit_id, is_active=True).first()
    if unit is None:
        errors.setdefault("unit", []).append("Choose an active unit.")
    if (product.pack_unit_id is None) != (product.pack_size is None):
        errors.setdefault("pack_size", []).append(
            "Enter both the pack unit and how many base units are in one pack."
        )
    elif product.pack_unit_id is not None:
        if product.pack_unit_id == product.unit_id:
            errors.setdefault("pack_unit", []).append("The pack unit must differ from the unit.")
        elif not selectors.units().filter(pk=product.pack_unit_id).exists():
            errors.setdefault("pack_unit", []).append("Choose an existing unit.")
        if product.pack_size is not None and product.pack_size <= 0:
            errors.setdefault("pack_size", []).append("Enter a pack size above 0.")
    for name in ("min_order_qty", "order_multiple"):
        value = getattr(product, name)
        if value is None or value <= 0:
            errors.setdefault(name, []).append("Enter a quantity above 0.")
        elif unit is not None and not unit.allows_decimal and value != value.to_integral_value():
            errors.setdefault(name, []).append(f"{unit.code} is counted in whole numbers.")
    if product.base_price is None or product.base_price < 0:
        errors.setdefault("base_price", []).append("Enter a price of 0 or more.")
    if product.cost_price is not None and product.cost_price < 0:
        errors.setdefault("cost_price", []).append("Enter a cost of 0 or more.")
    if product.mrp is not None and product.mrp < 0:
        errors.setdefault("mrp", []).append("Enter an MRP of 0 or more.")
    if product.reorder_level is not None and product.reorder_level < 0:
        errors.setdefault("reorder_level", []).append("Enter 0 or more.")
    if not product.code.strip():
        errors.setdefault("code", []).append("Enter a product code.")
    if not product.name.strip():
        errors.setdefault("name", []).append("Enter a product name.")


def price_warnings(product: Product, gst_rate: Decimal | None) -> list[Warning]:
    """PLAN M11: a selling price above MRP is allowed, with a warning. MRP includes GST, so the
    price is compared as the retailer pays it."""
    warnings: list[Warning] = []
    if product.mrp is not None and gst_rate is not None:
        include_gst = bool(get_setting("tax.prices_include_gst", require_tenant_id()))
        paid = (
            product.base_price
            if include_gst
            else (product.base_price * (Decimal("100") + gst_rate) / Decimal("100")).quantize(
                Decimal("0.01")
            )
        )
        if paid > product.mrp:
            warnings.append(
                Warning(
                    "PRICE_ABOVE_MRP",
                    f"The price including GST (₹{paid}) is above the MRP (₹{product.mrp}).",
                    {"price_with_gst": str(paid), "mrp": str(product.mrp)},
                )
            )
    if gst_rate is not None:
        hint = selectors.hint_differs(product.hsn_code, gst_rate)
        if hint is not None:
            warnings.append(
                Warning(
                    "HSN_RATE_DIFFERS",
                    f"HSN {hint.hsn_prefix} usually has GST {hint.gst_rate.normalize():f}%. "
                    "Check the rate.",
                    {"suggested_rate": str(hint.gst_rate), "hsn_prefix": hint.hsn_prefix},
                )
            )
    return warnings


def _snapshot(product: Product) -> dict[str, Any]:
    return {f: getattr(product, f) for f in PRODUCT_FIELDS}


def _save_product(product: Product) -> None:
    try:
        with transaction.atomic():
            product.save()
    except IntegrityError as exc:
        if "uniq_product_code" in str(exc):
            raise InvalidFields({"code": ["Another product already uses this code."]}) from exc
        raise


@transaction.atomic
def _check_cost_permission(data: dict[str, Any], by: User) -> None:
    if "cost_price" in data and not by.has_permission_code(COST_PERMISSION):
        raise InvalidFields(
            {"cost_price": ["Only staff with the pricing permission can set the cost price."]}
        )


def create_product(
    data: dict[str, Any],
    *,
    gst_rate: Decimal,
    cess_type_id: UUID | None = None,
    cess_rate: Decimal = Decimal("0"),
    barcodes: Iterable[str] = (),
    by: User,
) -> tuple[Product, list[Warning]]:
    """A product with its first GST rate (effective today, so it can be sold at once)."""
    if data.get("cost_price") is None:
        data = {k: v for k, v in data.items() if k != "cost_price"}
    _check_cost_permission(data, by)
    product = Product(created_by=by)
    for key in PRODUCT_FIELDS:
        if key in data:
            setattr(product, key, data[key])
    product.code = (product.code or "").strip()
    product.name = " ".join((product.name or "").split())
    product.hsn_code = "".join((product.hsn_code or "").split())
    product.tags = _clean_tags(product.tags or [])
    _normalize_numbers(product)
    errors: dict[str, list[str]] = {}
    _validate_product(product, errors)
    try:
        _active_rate(gst_rate)
        cess, cess_rate = _cess(cess_type_id, cess_rate)
    except InvalidFields as exc:
        errors.update(exc.details["fields"])
        cess = None
    if errors:
        raise InvalidFields(errors)
    _save_product(product)
    inventory.ensure_levels_exist([product.pk], inventory.default_warehouse())
    ProductTaxRate.objects.create(
        product=product,
        gst_rate=gst_rate,
        cess_type=cess,
        cess_rate=cess_rate,
        effective_from=today_ist(),
        reason="Initial rate",
        created_by=by,
    )
    for barcode in barcodes:
        add_barcode(product.pk, barcode, by=by)
    audit.record(
        "catalog.product_created",
        target=product,
        target_repr=f"{product.code} {product.name}",
        changes=audit.diff({}, {**_snapshot(product), "gst_rate": gst_rate}),
    )
    return product, price_warnings(product, gst_rate)


@transaction.atomic
def update_product(
    product_id: UUID, changes: dict[str, Any], *, by: User
) -> tuple[Product, list[Warning]]:
    levels = {}
    if "reorder_level" in changes and Product.objects.filter(pk=product_id).exists():
        # Stock level before the product row (the inventory lock order), to re-check alerts.
        levels = inventory.lock_levels([product_id], inventory.default_warehouse())
    product = (
        Product.objects.select_for_update().filter(pk=product_id, deleted_at__isnull=True).first()
    )
    if product is None:
        raise NotFound()
    _check_cost_permission(changes, by)
    before = _snapshot(product)
    for key in PRODUCT_FIELDS:
        if key in changes:
            setattr(product, key, changes[key])
    product.code = product.code.strip()
    product.name = " ".join(product.name.split())
    product.hsn_code = "".join(product.hsn_code.split())
    product.tags = _clean_tags(product.tags or [])
    _normalize_numbers(product)
    errors: dict[str, list[str]] = {}
    _validate_product(product, errors)
    if errors:
        raise InvalidFields(errors)
    diff = audit.diff(before, _snapshot(product))
    if diff:
        _save_product(product)
        repr_ = f"{product.code} {product.name}"
        audit.record("catalog.product_updated", target=product, target_repr=repr_, changes=diff)
        prices = {k: v for k, v in diff.items() if k in PRICE_FIELDS}
        if prices:  # the sensitive part, separately searchable in the audit log
            audit.record(
                "catalog.product_price_changed", target=product, target_repr=repr_, changes=prices
            )
        if "reorder_level" in diff:
            for level in levels.values():
                inventory_alerts.evaluate(level, product.reorder_level)
    rate = selectors.tax_rate_on(product.pk)
    return product, price_warnings(product, rate.gst_rate if rate else None)


@transaction.atomic
def delete_product(product_id: UUID, *, by: User) -> None:
    product = selectors.products().filter(pk=product_id).first()
    if product is None:
        raise NotFound()
    barcodes = list(product.barcodes.values_list("barcode", flat=True))
    product.barcodes.all().delete()  # a real-world barcode may be reused by a new product
    product.deleted_at, product.is_active = timezone.now(), False
    product.save(update_fields=["deleted_at", "is_active", "updated_at"])
    audit.record(
        "catalog.product_deleted",
        target=product,
        target_repr=f"{product.code} {product.name}",
        metadata={"barcodes": barcodes},
    )


# --- Barcodes -----------------------------------------------------------------------------------


@transaction.atomic
def add_barcode(product_id: UUID, barcode: str, *, by: User) -> ProductBarcode:
    barcode = "".join(barcode.split())
    if not barcode or len(barcode) > 64:
        raise InvalidFields({"barcode": ["Enter a barcode of up to 64 characters."]})
    product = selectors.products().filter(pk=product_id).first()
    if product is None:
        raise NotFound()
    try:
        with transaction.atomic():
            row: ProductBarcode = ProductBarcode.objects.create(
                product=product, barcode=barcode, created_by=by
            )
    except IntegrityError as exc:
        raise InvalidFields({"barcode": ["Another product already has this barcode."]}) from exc
    audit.record("catalog.barcode_added", target=product, metadata={"barcode": barcode})
    return row


@transaction.atomic
def remove_barcode(product_id: UUID, barcode_id: UUID, *, by: User) -> None:
    row = ProductBarcode.objects.filter(pk=barcode_id, product_id=product_id).first()
    if row is None:
        raise NotFound()
    row.delete()
    audit.record(
        "catalog.barcode_removed",
        target_type="catalog.product",
        target_id=product_id,
        metadata={"barcode": row.barcode},
    )


# --- Bulk actions -------------------------------------------------------------------------------

BULK_ACTIONS = (
    "activate",
    "deactivate",
    "show_in_shop",
    "hide_from_shop",
    "set_category",
    "set_brand",
)
BULK_LIMIT = 1000


@transaction.atomic
def bulk_update(
    product_ids: list[UUID], action: str, *, value: UUID | None = None, by: User
) -> int:
    if action not in BULK_ACTIONS:
        raise InvalidFields({"action": ["Choose a supported action."]})
    if not product_ids or len(product_ids) > BULK_LIMIT:
        raise InvalidFields({"product_ids": [f"Select 1 to {BULK_LIMIT} products."]})
    field_name, new_value = {
        "activate": ("is_active", True),
        "deactivate": ("is_active", False),
        "show_in_shop": ("show_in_shop", True),
        "hide_from_shop": ("show_in_shop", False),
        "set_category": ("category_id", value),
        "set_brand": ("brand_id", value),
    }[action]
    if action == "set_category" and value and selectors.category(value) is None:
        raise InvalidFields({"value": ["Choose an existing category."]})
    if action == "set_brand" and value and not selectors.brands().filter(pk=value).exists():
        raise InvalidFields({"value": ["Choose an existing brand."]})
    products = list(selectors.products().filter(pk__in=product_ids).select_for_update(of=("self",)))
    changed = 0
    for product in products:
        if getattr(product, field_name) != new_value:
            setattr(product, field_name, new_value)
            product.save(update_fields=[field_name, "updated_at"])
            changed += 1
    audit.record(
        "catalog.products_bulk_updated",
        target_type="catalog.product",
        metadata={
            "action": action,
            "value": str(value) if value else None,
            "count": changed,
            "product_ids": [str(p.pk) for p in products][:200],
        },
    )
    return changed


# --- GST rate changes (ADR-034) -----------------------------------------------------------------


def _check_new_rate(gst_rate: Decimal, effective_from: date) -> None:
    errors: dict[str, list[str]] = {}
    try:
        _active_rate(gst_rate)
    except InvalidFields as exc:
        errors.update(exc.details["fields"])
    if effective_from < today_ist():
        errors["effective_from"] = [
            "A rate change can't start in the past. Choose today or a later date."
        ]
    if errors:
        raise InvalidFields(errors)


@transaction.atomic
def schedule_tax_rate(
    product_id: UUID,
    *,
    gst_rate: Decimal,
    effective_from: date,
    cess_type_id: UUID | None = None,
    cess_rate: Decimal = Decimal("0"),
    reason: str = "",
    by: User,
) -> ProductTaxRate:
    product = (
        Product.objects.select_for_update().filter(pk=product_id, deleted_at__isnull=True).first()
    )
    if product is None:
        raise NotFound()
    _check_new_rate(gst_rate, effective_from)
    cess, cess_rate = _cess(cess_type_id, cess_rate)
    row: ProductTaxRate
    try:
        with transaction.atomic():
            row = ProductTaxRate.objects.create(
                product=product,
                gst_rate=gst_rate,
                cess_type=cess,
                cess_rate=cess_rate,
                effective_from=effective_from,
                reason=reason.strip()[:200],
                created_by=by,
            )
    except IntegrityError as exc:
        raise InvalidFields(
            {"effective_from": ["A change already starts on this date. Cancel it first."]}
        ) from exc
    audit.record(
        "catalog.tax_rate_scheduled",
        target=product,
        target_repr=f"{product.code} {product.name}",
        changes={"gst_rate": [None, str(gst_rate)], "cess_rate": [None, str(cess_rate)]},
        metadata={"effective_from": effective_from.isoformat(), "reason": row.reason},
    )
    return row


@transaction.atomic
def cancel_tax_rate(product_id: UUID, rate_id: UUID, *, reason: str, by: User) -> ProductTaxRate:
    row: ProductTaxRate | None = (
        ProductTaxRate.objects.select_for_update()
        .filter(pk=rate_id, product_id=product_id, product__deleted_at__isnull=True)
        .select_related("product")
        .first()
    )
    if row is None:
        raise NotFound()
    if row.cancelled_at is not None or row.effective_from <= today_ist():
        raise TaxRateNotCancellable()
    if not reason.strip():
        raise InvalidFields({"reason": ["Enter why this change is cancelled."]})
    row.cancelled_at, row.cancelled_by, row.cancel_reason = timezone.now(), by, reason.strip()[:200]
    row.save(update_fields=["cancelled_at", "cancelled_by", "cancel_reason"])
    audit.record(
        "catalog.tax_rate_cancelled",
        target=row.product,
        target_repr=f"{row.product.code} {row.product.name}",
        metadata={
            "effective_from": row.effective_from.isoformat(),
            "gst_rate": str(row.gst_rate),
            "reason": row.cancel_reason,
        },
    )
    return row


@dataclass(frozen=True)
class RateScheduleFilter:
    hsn_prefix: str = ""
    category_id: UUID | None = None
    product_ids: tuple[UUID, ...] = ()


def _schedule_targets(f: RateScheduleFilter, effective_from: date) -> tuple[list[Product], int]:
    """Matching products, and how many already have a change starting that day (skipped)."""
    if not (f.hsn_prefix or f.category_id or f.product_ids):
        raise InvalidFields({"filter": ["Choose products by HSN, category or selection."]})
    qs = selectors.products()
    if f.hsn_prefix:
        qs = qs.filter(hsn_code__startswith=f.hsn_prefix)
    if f.category_id:
        qs = qs.filter(category_id__in=selectors.descendant_ids(f.category_id))
    if f.product_ids:
        qs = qs.filter(pk__in=f.product_ids)
    matched = list(qs.order_by("code"))
    taken = set(
        ProductTaxRate.objects.filter(
            product_id__in=[p.pk for p in matched],
            effective_from=effective_from,
            cancelled_at__isnull=True,
        ).values_list("product_id", flat=True)
    )
    return [p for p in matched if p.pk not in taken], len(taken)


def preview_rate_schedule(f: RateScheduleFilter, effective_from: date) -> dict[str, Any]:
    targets, skipped = _schedule_targets(f, effective_from)
    return {
        "count": len(targets),
        "skipped": skipped,
        "sample": [{"id": str(p.pk), "code": p.code, "name": p.name} for p in targets[:20]],
    }


@transaction.atomic
def commit_rate_schedule(
    f: RateScheduleFilter,
    *,
    gst_rate: Decimal,
    effective_from: date,
    expected_count: int,
    cess_type_id: UUID | None = None,
    cess_rate: Decimal = Decimal("0"),
    reason: str = "",
    by: User,
) -> int:
    """Schedule the change for every matching product, exactly as previewed."""
    _check_new_rate(gst_rate, effective_from)
    cess, cess_rate = _cess(cess_type_id, cess_rate)
    targets, _ = _schedule_targets(f, effective_from)
    if len(targets) != expected_count:
        raise PreviewOutOfDate()
    ProductTaxRate.objects.bulk_create(
        [
            ProductTaxRate(
                tenant_id=require_tenant_id(),
                product=p,
                gst_rate=gst_rate,
                cess_type=cess,
                cess_rate=cess_rate,
                effective_from=effective_from,
                reason=reason.strip()[:200],
                created_by=by,
            )
            for p in targets
        ]
    )
    audit.record(
        "catalog.tax_rate_bulk_scheduled",
        target_type="catalog.product",
        metadata={
            "count": len(targets),
            "gst_rate": str(gst_rate),
            "cess_rate": str(cess_rate),
            "effective_from": effective_from.isoformat(),
            "hsn_prefix": f.hsn_prefix,
            "category_id": str(f.category_id) if f.category_id else None,
            "product_ids": [str(p.pk) for p in targets][:200],
            "reason": reason.strip()[:200],
        },
    )
    return len(targets)


# --- Product images (ADR-034) -------------------------------------------------------------------

MAX_IMAGES_PER_PRODUCT = 10


@transaction.atomic
def upload_image(
    product_id: UUID, upload: "UploadedFile[bytes]", *, alt_text: str = "", by: User
) -> ProductImage:
    """Store the validated original privately and resize it in the background."""
    from apps.catalog import images
    from apps.catalog.tasks import process_product_image

    product = selectors.products().filter(pk=product_id).first()
    if product is None:
        raise NotFound()
    if product.images.count() >= MAX_IMAGES_PER_PRODUCT:
        raise InvalidFields(
            {"file": [f"A product can have at most {MAX_IMAGES_PER_PRODUCT} images."]}
        )
    valid = validate_image(
        upload, max_bytes=images.PRODUCT_IMAGE_MAX_BYTES, max_side=images.PRODUCT_IMAGE_MAX_SIDE
    )
    image = ProductImage(
        product=product,
        alt_text=alt_text.strip()[:200],
        created_by=by,
        sort_order=(product.images.aggregate(m=Max("sort_order"))["m"] or 0) + 1,
    )
    tenant_id = require_tenant_id()
    image.original_key = images.original_key(tenant_id, product.pk, image.pk, valid.extension)
    # Stored before the row; if the transaction then fails the file is an unreferenced orphan.
    get_storage().put(image.original_key, valid.data, valid.content_type)
    image.save()
    audit.record(
        "catalog.image_uploaded",
        target=product,
        target_repr=f"{product.code} {product.name}",
        metadata={"image_id": str(image.pk), "bytes": len(valid.data)},
    )
    image_id, tenant = str(image.pk), str(tenant_id)
    transaction.on_commit(lambda: process_product_image.delay(image_id=image_id, tenant_id=tenant))
    return image


def process_image(image_id: str) -> None:
    """Resize (no transaction held), then record the variants in a short transaction. Runs in a
    task that has set the tenant, but no transaction."""
    from apps.catalog import images

    tenant_id = require_tenant_id()
    with tenant_transaction(tenant_id):
        image = ProductImage.objects.filter(pk=image_id).first()
        if image is None or image.status == ProductImage.Status.READY:
            return
        key, product_id = image.original_key, image.product_id
    original = get_storage().get(key)
    try:
        rendered = images.render_variants(original)
    except (OSError, ValueError, Image.DecompressionBombError):
        mark_image_failed(image_id)
        return
    stored = images.store_variants(images.variant_prefix(tenant_id, product_id, original), rendered)
    with tenant_transaction(tenant_id):
        updated = ProductImage.objects.filter(pk=image_id).update(
            variants=stored, status=ProductImage.Status.READY, updated_at=timezone.now()
        )
    if not updated:  # deleted while processing: remove what was just written
        for variant in stored.values():
            get_storage().delete_public(variant["key"])


def mark_image_failed(image_id: str) -> None:
    with tenant_transaction(require_tenant_id()):
        ProductImage.objects.filter(pk=image_id).update(
            status=ProductImage.Status.FAILED, updated_at=timezone.now()
        )


@transaction.atomic
def update_image(
    product_id: UUID, image_id: UUID, *, sort_order: int | None, alt_text: str | None, by: User
) -> ProductImage:
    image: ProductImage | None = ProductImage.objects.filter(
        pk=image_id, product_id=product_id, product__deleted_at__isnull=True
    ).first()
    if image is None:
        raise NotFound()
    if sort_order is not None:
        image.sort_order = sort_order
    if alt_text is not None:
        image.alt_text = alt_text.strip()[:200]
    image.save(update_fields=["sort_order", "alt_text", "updated_at"])
    return image


@transaction.atomic
def delete_image(product_id: UUID, image_id: UUID, *, by: User) -> None:
    from apps.catalog.tasks import delete_image_objects

    image = (
        ProductImage.objects.filter(
            pk=image_id, product_id=product_id, product__deleted_at__isnull=True
        )
        .select_related("product")
        .first()
    )
    if image is None:
        raise NotFound()
    original, public = image.original_key, [v["key"] for v in image.variants.values()]
    product = image.product
    image.delete()
    audit.record(
        "catalog.image_deleted",
        target=product,
        target_repr=f"{product.code} {product.name}",
        metadata={"image_id": str(image_id)},
    )
    transaction.on_commit(
        lambda: delete_image_objects.delay(original_key=original, public_keys=public)
    )
