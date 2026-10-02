"""Pricing writes (spec 5.6, PLAN §2.5). Every price change is audited (CLAUDE.md §4). How a price
is resolved for a retailer is ``resolve.resolve_price`` (one place only)."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.audit import services as audit
from apps.catalog import selectors as catalog
from apps.catalog.models import Product
from apps.catalog.services import InUse, Warning
from apps.pricing import free_goods
from apps.pricing.models import (
    DiscountRule,
    DiscountSlab,
    FreeGoodsScheme,
    PriceList,
    PriceListItem,
    RetailerPrice,
)
from apps.retailers.models import Retailer
from common.errors import InvalidFields, NotFound

MAX_BULK_ITEMS = 5000


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


# --- Price lists --------------------------------------------------------------------------------


def _price_list(price_list_id: UUID, *, lock: bool = False) -> PriceList:
    qs = PriceList.objects.filter(pk=price_list_id, deleted_at__isnull=True)
    found: PriceList | None = (qs.select_for_update() if lock else qs).first()
    if found is None:
        raise NotFound()
    return found


@transaction.atomic
def save_price_list(
    price_list_id: UUID | None, *, name: str, code: str = "", description: str = "", by: User
) -> PriceList:
    name = " ".join(name.split())
    if not name:
        raise InvalidFields({"name": [_("Enter a name.")]})
    if price_list_id is None:
        price_list = PriceList(created_by=by)
        before: dict[str, Any] = {}
    else:
        price_list = _price_list(price_list_id, lock=True)
        before = {
            "name": price_list.name,
            "code": price_list.code,
            "description": price_list.description,
        }
    price_list.name, price_list.code = name, code.strip()[:30]
    price_list.description = description.strip()[:300]
    try:
        with transaction.atomic():
            price_list.save()
    except IntegrityError as exc:
        raise InvalidFields({"name": [_("Another price list has this name.")]}) from exc
    after = {
        "name": price_list.name,
        "code": price_list.code,
        "description": price_list.description,
    }
    changes = audit.diff(before, after)
    if changes:
        audit.record(
            "pricing.price_list_created" if not before else "pricing.price_list_updated",
            target=price_list,
            target_repr=price_list.name,
            changes=changes,
        )
    return price_list


@transaction.atomic
def delete_price_list(price_list_id: UUID, *, by: User) -> None:
    """Refused while shops use it: they would silently fall back to the base price."""
    price_list = _price_list(price_list_id, lock=True)
    shops = Retailer.objects.filter(price_list=price_list, deleted_at__isnull=True).count()
    if shops:
        raise InUse(
            _("%(shops)s shop(s) use this price list. Move them to another list first.")
            % {"shops": shops}
        )
    if DiscountRule.objects.filter(price_list=price_list).exists():
        raise InUse(_("Some discount rules are for this price list. Change or delete them first."))
    price_list.deleted_at, price_list.is_active = timezone.now(), False
    price_list.save(update_fields=["deleted_at", "is_active", "updated_at"])
    audit.record("pricing.price_list_deleted", target=price_list, target_repr=price_list.name)


@dataclass(frozen=True)
class ItemInput:
    product_id: UUID
    price: Decimal


@transaction.atomic
def upsert_items(
    price_list_id: UUID, items: list[ItemInput], *, by: User
) -> tuple[int, list[Warning]]:
    """Set prices for many products at once; returns how many changed and any free-goods
    warning. Every change is in one audit entry with old → new per product code."""
    price_list = _price_list(price_list_id, lock=True)
    if len(items) > MAX_BULK_ITEMS:
        raise InvalidFields(
            {
                "items": [
                    _("Send at most %(max_bulk_items)s prices at a time.")
                    % {"max_bulk_items": format(MAX_BULK_ITEMS, ",")}
                ]
            }
        )
    errors: dict[str, list[str]] = {}
    seen: set[UUID] = set()
    for index, item in enumerate(items):
        if item.price < 0:
            errors.setdefault(f"items.{index}.price", []).append(_("Enter 0 or more."))
        if item.product_id in seen:
            errors.setdefault(f"items.{index}.product", []).append(
                _("This product is listed twice.")
            )
        seen.add(item.product_id)
    products = {p.pk: p for p in catalog.products().filter(pk__in=[i.product_id for i in items])}
    for index, item in enumerate(items):
        if item.product_id not in products:
            errors.setdefault(f"items.{index}.product", []).append(_("Choose an existing product."))
    if errors:
        raise InvalidFields(errors)
    current = {
        row.product_id: row
        for row in PriceListItem.objects.select_for_update().filter(
            price_list=price_list, product_id__in=list(seen)
        )
    }
    changes: dict[str, list[Any]] = {}
    for item in items:
        row = current.get(item.product_id)
        code = products[item.product_id].code
        if row is None:
            PriceListItem.objects.create(
                price_list=price_list, product_id=item.product_id, price=item.price, created_by=by
            )
            changes[code] = [None, _money(item.price)]
        elif row.price != item.price:
            changes[code] = [_money(row.price), _money(item.price)]
            row.price = item.price
            row.save(update_fields=["price", "updated_at"])
    if changes:
        audit.record(
            "pricing.price_list_prices_changed",
            target=price_list,
            target_repr=price_list.name,
            changes=dict(list(changes.items())[:500]),
            metadata={"count": len(changes)},
        )
    zero = [i.product_id for i in items if i.price == 0]
    return len(changes), free_goods.price_list_warnings(price_list, zero) if zero else []


@transaction.atomic
def delete_item(price_list_id: UUID, product_id: UUID, *, by: User) -> None:
    price_list = _price_list(price_list_id, lock=True)
    row = (
        PriceListItem.objects.filter(price_list=price_list, product_id=product_id)
        .select_related("product")
        .first()
    )
    if row is None:
        raise NotFound()
    code, price = row.product.code, row.price
    row.delete()
    audit.record(
        "pricing.price_list_prices_changed",
        target=price_list,
        target_repr=price_list.name,
        changes={code: [_money(price), None]},
    )


# --- Retailer special prices --------------------------------------------------------------------


@transaction.atomic
def save_retailer_price(
    price_id: UUID | None,
    *,
    retailer_id: UUID | None = None,
    product_id: UUID | None = None,
    price: Decimal,
    note: str = "",
    by: User,
) -> tuple[RetailerPrice, list[Warning]]:
    if price < 0:
        raise InvalidFields({"price": [_("Enter 0 or more.")]})
    if price_id is None:
        retailer = (
            Retailer.objects.filter(pk=retailer_id, deleted_at__isnull=True).first()
            if retailer_id
            else None
        )
        product = catalog.products().filter(pk=product_id).first() if product_id else None
        errors: dict[str, list[str]] = {}
        if retailer is None:
            errors["retailer"] = [_("Choose an existing shop.")]
        if product is None:
            errors["product"] = [_("Choose an existing product.")]
        if errors:
            raise InvalidFields(errors)
        row = RetailerPrice(
            retailer=retailer, product=product, price=price, note=note.strip()[:200], created_by=by
        )
        old = None
        try:
            with transaction.atomic():
                row.save()
        except IntegrityError as exc:
            raise InvalidFields(
                {"product": [_("This shop already has a special price for this product.")]}
            ) from exc
    else:
        found = RetailerPrice.objects.select_for_update().filter(pk=price_id).first()
        if found is None:
            raise NotFound()
        row, old = found, found.price
        row.price, row.note = price, note.strip()[:200]
        row.save(update_fields=["price", "note", "updated_at"])
    if old != row.price:
        audit.record(
            "pricing.retailer_price_changed",
            target=row.retailer,
            target_repr=f"{row.retailer.code} {row.retailer.shop_name}",
            changes={
                row.product.code: [_money(old) if old is not None else None, _money(row.price)]
            },
        )
    return row, free_goods.special_price_warnings(row)


@transaction.atomic
def delete_retailer_price(price_id: UUID, *, by: User) -> None:
    row = RetailerPrice.objects.select_related("retailer", "product").filter(pk=price_id).first()
    if row is None:
        raise NotFound()
    row.delete()
    audit.record(
        "pricing.retailer_price_changed",
        target=row.retailer,
        target_repr=f"{row.retailer.code} {row.retailer.shop_name}",
        changes={row.product.code: [_money(row.price), None]},
    )


# --- Discount rules -----------------------------------------------------------------------------

RULE_FIELDS = (
    "name",
    "discount_type",
    "value",
    "scope_type",
    "product_id",
    "category_id",
    "brand_id",
    "audience_type",
    "price_list_id",
    "retailer_id",
    "valid_from",
    "valid_to",
    "is_active",
)
SCOPE_TARGET = {"PRODUCT": "product_id", "CATEGORY": "category_id", "BRAND": "brand_id"}
AUDIENCE_TARGET = {"PRICE_LIST": "price_list_id", "RETAILER": "retailer_id"}


@dataclass(frozen=True)
class SlabInput:
    min_qty: Decimal
    value: Decimal


def check_value(kind: str, value: Decimal, field: str, errors: dict[str, list[str]]) -> None:
    if kind == DiscountRule.Type.PERCENT and not Decimal("0") < value <= Decimal("100"):
        errors.setdefault(field, []).append(_("Enter a percentage above 0 and up to 100."))
    elif kind == DiscountRule.Type.FLAT_PER_UNIT and value <= 0:
        errors.setdefault(field, []).append(_("Enter an amount above 0."))


def _check_targets(rule: DiscountRule, errors: dict[str, list[str]]) -> None:
    for scope, attr in SCOPE_TARGET.items():
        if rule.scope_type != scope:
            setattr(rule, attr, None)
    for audience, attr in AUDIENCE_TARGET.items():
        if rule.audience_type != audience:
            setattr(rule, attr, None)
    lookups = {
        "product_id": (catalog.products(), "product"),
        "category_id": (catalog.categories(), "category"),
        "brand_id": (catalog.brands(), "brand"),
        "price_list_id": (PriceList.objects.filter(deleted_at__isnull=True), "price list"),
        "retailer_id": (Retailer.objects.filter(deleted_at__isnull=True), "shop"),
    }
    needed = [SCOPE_TARGET.get(rule.scope_type), AUDIENCE_TARGET.get(rule.audience_type)]
    for attr in filter(None, needed):
        qs, label = lookups[attr]
        value = getattr(rule, attr)
        field = attr.removesuffix("_id")
        if value is None:
            errors.setdefault(field, []).append(_("Choose the %(label)s.") % {"label": label})
        elif not qs.filter(pk=value).exists():
            errors.setdefault(field, []).append(
                _("Choose an existing %(label)s.") % {"label": label}
            )


@transaction.atomic
def save_discount_rule(
    rule_id: UUID | None, data: dict[str, Any], slabs: list[SlabInput] | None, *, by: User
) -> tuple[DiscountRule, list[Warning]]:
    """``slabs=None`` keeps the rule's slabs; a list replaces them ([] removes them)."""
    if rule_id is None:
        rule = DiscountRule(created_by=by)
        before: dict[str, Any] = {}
    else:
        found = DiscountRule.objects.select_for_update().filter(pk=rule_id).first()
        if found is None:
            raise NotFound()
        rule = found
        before = {f: getattr(rule, f) for f in RULE_FIELDS}
    for key in RULE_FIELDS:
        if key in data:
            setattr(rule, key, data[key])
    rule.name = " ".join((rule.name or "").split())
    errors: dict[str, list[str]] = {}
    if not rule.name:
        errors["name"] = [_("Enter a name.")]
    if rule.discount_type not in DiscountRule.Type.values:
        errors["discount_type"] = [_("Choose percentage or rupees off per unit.")]
    if rule.scope_type not in DiscountRule.Scope.values:
        errors["scope_type"] = [_("Choose what the discount applies to.")]
    if rule.audience_type not in DiscountRule.Audience.values:
        errors["audience_type"] = [_("Choose which shops get it.")]
    if not errors:
        _check_targets(rule, errors)
    if rule.valid_from and rule.valid_to and rule.valid_to < rule.valid_from:
        errors["valid_to"] = [_("The end date must be on or after the start date.")]
    existing_slabs = list(rule.slabs.all()) if rule.pk and slabs is None else None
    new_slabs = (
        slabs
        if slabs is not None
        else [SlabInput(s.min_qty, s.value) for s in existing_slabs or []]
    )
    if new_slabs:
        quantities = [s.min_qty for s in new_slabs]
        if len(set(quantities)) != len(quantities):
            errors["slabs"] = [_("Each slab needs a different minimum quantity.")]
        for index, slab in enumerate(new_slabs):
            if slab.min_qty <= 0:
                errors.setdefault(f"slabs.{index}.min_qty", []).append(
                    _("Enter a quantity above 0.")
                )
            check_value(rule.discount_type, slab.value, f"slabs.{index}.value", errors)
        rule.value = Decimal("0")  # slabs carry the values
    else:
        check_value(rule.discount_type, Decimal(rule.value or 0), "value", errors)
    if errors:
        raise InvalidFields(errors)
    rule.save()
    if slabs is not None:
        rule.slabs.all().delete()
        DiscountSlab.objects.bulk_create(
            [
                DiscountSlab(
                    tenant_id=rule.tenant_id,
                    rule=rule,
                    min_qty=s.min_qty,
                    value=s.value,
                    created_by=by,
                )
                for s in sorted(slabs, key=lambda s: s.min_qty)
            ]
        )
    changes = audit.diff(before, {f: getattr(rule, f) for f in RULE_FIELDS})
    if slabs is not None:
        changes["slabs"] = [
            [[str(s.min_qty), str(s.value)] for s in existing_slabs or []] if before else None,
            [[str(s.min_qty), str(s.value)] for s in slabs],
        ]
    audit.record(
        "pricing.discount_rule_created" if not before else "pricing.discount_rule_updated",
        target=rule,
        target_repr=rule.name,
        changes=changes,
    )
    return rule, free_goods.rule_warnings(rule)


@transaction.atomic
def delete_discount_rule(rule_id: UUID, *, by: User) -> None:
    rule = DiscountRule.objects.filter(pk=rule_id).first()
    if rule is None:
        raise NotFound()
    name = rule.name
    rule.delete()
    audit.record(
        "pricing.discount_rule_deleted",
        target_type="pricing.discountrule",
        target_id=rule_id,
        target_repr=name,
    )


# --- Free-goods schemes (ADR-056 item 7) ----------------------------------------------------------

SCHEME_FIELDS = (
    "name",
    "buy_product_id",
    "buy_qty",
    "free_product_id",
    "free_qty",
    "repeat",
    "max_free_qty",
    "audience_type",
    "price_list_id",
    "retailer_id",
    "valid_from",
    "valid_to",
    "is_active",
)


def _check_scheme_quantities(scheme: FreeGoodsScheme, errors: dict[str, list[str]]) -> None:
    products = {
        p.pk: p
        for p in catalog.products()
        .filter(pk__in=[scheme.buy_product_id, scheme.free_product_id])
        .select_related("unit")
    }
    checks = (
        ("buy_product", scheme.buy_product_id, "buy_qty", scheme.buy_qty),
        ("free_product", scheme.free_product_id, "free_qty", scheme.free_qty),
        ("free_product", scheme.free_product_id, "max_free_qty", scheme.max_free_qty),
    )
    for product_field, product_id, field, value in checks:
        product = products.get(product_id) if product_id else None
        if field != "max_free_qty" and product is None:
            errors.setdefault(product_field, []).append(_("Choose an existing product."))
        if value is None:
            if field != "max_free_qty":
                errors.setdefault(field, []).append(_("Enter a quantity above 0."))
            continue
        if value <= 0:
            errors.setdefault(field, []).append(_("Enter a quantity above 0."))
        elif product is not None and not product.unit.allows_decimal and value % 1:
            errors.setdefault(field, []).append(
                _("Enter whole %(code)s.") % {"code": product.unit.code}
            )
    if (
        scheme.max_free_qty is not None
        and scheme.free_qty
        and scheme.max_free_qty < scheme.free_qty
    ):
        errors.setdefault("max_free_qty", []).append(
            _("The most free on one order can't be less than the free quantity.")
        )


@transaction.atomic
def save_scheme(scheme_id: UUID | None, data: dict[str, Any], *, by: User) -> FreeGoodsScheme:
    """Create or change a scheme; every change is audited. Orders already placed keep the terms
    they were given."""
    if scheme_id is None:
        scheme = FreeGoodsScheme(created_by=by)
        before: dict[str, Any] = {}
    else:
        found = FreeGoodsScheme.objects.select_for_update().filter(pk=scheme_id).first()
        if found is None:
            raise NotFound()
        scheme = found
        before = {f: getattr(scheme, f) for f in SCHEME_FIELDS}
    for key in SCHEME_FIELDS:
        if key in data:
            setattr(scheme, key, data[key])
    scheme.name = " ".join((scheme.name or "").split())
    errors: dict[str, list[str]] = {}
    if not scheme.name:
        errors["name"] = [_("Enter a name.")]
    if scheme.audience_type not in DiscountRule.Audience.values:
        errors["audience_type"] = [_("Choose which shops get it.")]
    else:
        for audience, target in AUDIENCE_TARGET.items():
            if scheme.audience_type != audience:
                setattr(scheme, target, None)
        attr = AUDIENCE_TARGET.get(scheme.audience_type)
        lists = PriceList.objects.filter(pk=scheme.price_list_id, deleted_at__isnull=True)
        shops = Retailer.objects.filter(pk=scheme.retailer_id, deleted_at__isnull=True)
        if attr == "price_list_id" and not lists.exists():
            errors["price_list"] = [_("Choose an existing price list.")]
        elif attr == "retailer_id" and not shops.exists():
            errors["retailer"] = [_("Choose an existing shop.")]
    _check_scheme_quantities(scheme, errors)
    if scheme.valid_from and scheme.valid_to and scheme.valid_to < scheme.valid_from:
        errors["valid_to"] = [_("The end date must be on or after the start date.")]
    if errors:
        raise InvalidFields(errors)
    scheme.save()
    audit.record(
        "pricing.scheme_created" if not before else "pricing.scheme_updated",
        target=scheme,
        target_repr=scheme.name,
        changes=audit.diff(before, {f: getattr(scheme, f) for f in SCHEME_FIELDS}),
    )
    return scheme


@transaction.atomic
def delete_scheme(scheme_id: UUID, *, by: User) -> None:
    """Orders keep the scheme's name and terms on their free lines."""
    scheme = FreeGoodsScheme.objects.filter(pk=scheme_id).first()
    if scheme is None:
        raise NotFound()
    name = scheme.name
    scheme.delete()
    audit.record(
        "pricing.scheme_deleted",
        target_type="pricing.freegoodsscheme",
        target_id=scheme_id,
        target_repr=name,
    )


def assign_price_list(retailer: Retailer, price_list_id: UUID | None) -> None:
    """Validation for retailer edits, bulk actions and imports."""
    if (
        price_list_id is not None
        and not PriceList.objects.filter(pk=price_list_id, deleted_at__isnull=True).exists()
    ):
        raise InvalidFields({"price_list": [_("Choose an existing price list.")]})
    retailer.price_list_id = price_list_id


def products_exist(product_ids: list[UUID]) -> set[UUID]:
    return set(
        Product.objects.filter(pk__in=product_ids, deleted_at__isnull=True).values_list(
            "pk", flat=True
        )
    )
