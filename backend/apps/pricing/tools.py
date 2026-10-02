"""Per-shop pricing tools (ADR-037): the discount grid, copying pricing between shops, bulk
percentage changes to a price list, and the shop pricing report.

Every write goes through here in one transaction with one audit entry. Prices are never computed
anywhere but ``resolve_prices`` and ``billing.tax``.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Count, OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce
from django.utils.translation import gettext

from apps.accounts.models import User
from apps.audit import services as audit
from apps.billing.tax import adjust_price
from apps.catalog import selectors as catalog
from apps.catalog.models import Brand, Category, Product
from apps.catalog.services import PreviewOutOfDate, Warning
from apps.pricing import free_goods, resolve, services
from apps.pricing.models import DiscountRule, DiscountSlab, PriceList, PriceListItem, RetailerPrice
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.errors import InvalidFields, NotFound

ZERO = Decimal("0")


def _money(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _discount_text(rule: DiscountRule | None) -> str | None:
    if rule is None:
        return None
    if rule.discount_type == DiscountRule.Type.PERCENT:
        return f"{rule.value.normalize():f}%"
    return f"₹{rule.value:.2f} each"


# --- Discount grid: one simple rule per shop and product --------------------------------------


def is_simple(rule: DiscountRule) -> bool:
    """The grid's rule for a shop and product: no slabs and no dates (ADR-037 item 2)."""
    return (
        rule.audience_type == DiscountRule.Audience.RETAILER
        and rule.scope_type == DiscountRule.Scope.PRODUCT
        and rule.valid_from is None
        and rule.valid_to is None
        and not list(rule.slabs.all())
    )


def shop_product_rules(
    retailer: Retailer, product_ids: list[UUID]
) -> dict[UUID, list[DiscountRule]]:
    rules = (
        DiscountRule.objects.filter(
            audience_type=DiscountRule.Audience.RETAILER,
            retailer=retailer,
            scope_type=DiscountRule.Scope.PRODUCT,
            product_id__in=product_ids,
        )
        .prefetch_related("slabs")
        .order_by("created_at", "pk")
    )
    found: dict[UUID, list[DiscountRule]] = defaultdict(list)
    for rule in rules:
        assert rule.product_id is not None
        found[rule.product_id].append(rule)
    return found


def sellable_products(
    *, search: str = "", category_id: UUID | None = None, brand_id: UUID | None = None
) -> QuerySet[Product]:
    """Products that can be priced today (active, a GST rate in effect)."""
    qs = catalog.products(
        catalog.ProductFilters(
            search=search, category_id=category_id, brand_id=brand_id, is_active=True
        )
    ).filter(catalog.has_rate_on(today_ist()))
    return qs


@dataclass
class GridRow:
    product: Product
    simple: DiscountRule | None
    others: list[DiscountRule]
    result: resolve.PriceResult


def discount_grid(retailer: Retailer, products: list[Product]) -> list[GridRow]:
    rules = shop_product_rules(retailer, [p.pk for p in products])
    results = resolve.resolve_prices(retailer, [(p, p.min_order_qty) for p in products])
    rows: list[GridRow] = []
    for product, result in zip(products, results, strict=True):
        mine = rules.get(product.pk, [])
        simple = next((r for r in mine if is_simple(r)), None)
        rows.append(GridRow(product, simple, [r for r in mine if r is not simple], result))
    return rows


@dataclass(frozen=True)
class GridItem:
    product_id: UUID
    discount_type: str
    value: Decimal | None  # None or 0 removes the shop's discount on the product


def _grid_products(items: list[GridItem]) -> dict[UUID, Product]:
    errors: dict[str, list[str]] = {}
    products = {p.pk: p for p in sellable_products().filter(pk__in=[i.product_id for i in items])}
    seen: set[UUID] = set()
    for index, item in enumerate(items):
        if item.product_id not in products:
            errors.setdefault(f"items.{index}.product", []).append(
                gettext("Choose an existing product.")
            )
        if item.product_id in seen:
            errors.setdefault(f"items.{index}.product", []).append(
                gettext("This product is listed twice.")
            )
        seen.add(item.product_id)
        if item.discount_type not in DiscountRule.Type.values:
            errors.setdefault(f"items.{index}.discount_type", []).append(
                gettext("Choose percentage or rupees off per unit.")
            )
        elif item.value:
            services.check_value(item.discount_type, item.value, f"items.{index}.value", errors)
    if errors:
        raise InvalidFields(errors)
    return products


def preview_grid(
    retailer: Retailer, items: list[GridItem]
) -> list[tuple[Product, resolve.PriceResult]]:
    """Each product's price as if the entered discounts were saved; nothing is saved."""
    products = _grid_products(items)
    current = shop_product_rules(retailer, list(products))
    exclude = [r.pk for rules in current.values() for r in rules if is_simple(r)]
    extra = [
        resolve.hypothetical_rule(
            name="preview",
            discount_type=item.discount_type,
            value=item.value,
            scope_type=DiscountRule.Scope.PRODUCT,
            product_id=item.product_id,
            audience_type=DiscountRule.Audience.RETAILER,
            retailer_id=retailer.pk,
        )
        for item in items
        if item.value
    ]
    ordered = [products[i.product_id] for i in items]
    results = resolve.resolve_prices(
        retailer,
        [(p, p.min_order_qty) for p in ordered],
        extra_rules=extra,
        exclude_rule_ids=exclude,
    )
    return list(zip(ordered, results, strict=True))


def _simple_name(retailer: Retailer, product: Product) -> str:
    return f"{retailer.code} · {product.code}"


@transaction.atomic
def save_grid(retailer_id: UUID, items: list[GridItem], *, by: User) -> tuple[int, list[Warning]]:
    """Create, change or remove the shop's simple rule per product; one audit entry."""
    retailer = Retailer.objects.select_for_update().filter(pk=retailer_id).first()
    if retailer is None:
        raise NotFound()
    products = _grid_products(items)
    current = shop_product_rules(retailer, list(products))
    changes: dict[str, list[str | None]] = {}
    free = 0
    for item in items:
        product = products[item.product_id]
        simple = next((r for r in current.get(product.pk, []) if is_simple(r)), None)
        before = _discount_text(simple)
        if not item.value:
            if simple is not None:
                simple.delete()
                changes[product.code] = [before, None]
            continue
        if simple is None:
            simple = DiscountRule(
                name=_simple_name(retailer, product),
                scope_type=DiscountRule.Scope.PRODUCT,
                product=product,
                audience_type=DiscountRule.Audience.RETAILER,
                retailer=retailer,
                created_by=by,
            )
        was_active = simple.is_active and not simple._state.adding
        simple.discount_type, simple.value, simple.is_active = item.discount_type, item.value, True
        after = _discount_text(simple)
        if after != before or not was_active:
            simple.save()
            changes[product.code] = [before if was_active else None, after]
        if free_goods.rule_warnings(simple):
            free += 1
    if changes:
        audit.record(
            "pricing.shop_discounts_changed",
            target=retailer,
            target_repr=f"{retailer.code} {retailer.shop_name}",
            changes=dict(list(changes.items())[:500]),
            metadata={"count": len(changes)},
        )
    return len(changes), [free_goods.grid_warning(free)] if free else []


# --- Copy pricing between shops ------------------------------------------------------------------


class CopyMode:
    REPLACE = "REPLACE"
    ADD = "ADD"
    values = (REPLACE, ADD)


COPY_MODE_CHOICES = [
    (CopyMode.REPLACE, "Replace this shop's pricing"),
    (CopyMode.ADD, "Add to this shop's pricing"),
]


@dataclass
class CopyPlan:
    price_list: tuple[str | None, str | None] | None = None  # (from, to) when it changes
    prices_add: list[tuple[str, str, Decimal]] = field(default_factory=list)
    prices_update: list[tuple[str, str, Decimal, Decimal]] = field(default_factory=list)
    prices_remove: list[tuple[str, str, Decimal]] = field(default_factory=list)
    rules_add: list[str] = field(default_factory=list)
    rules_replace: list[str] = field(default_factory=list)
    rules_remove: list[str] = field(default_factory=list)

    @property
    def changes(self) -> int:
        return (
            (1 if self.price_list else 0)
            + len(self.prices_add)
            + len(self.prices_update)
            + len(self.prices_remove)
            + len(self.rules_add)
            + len(self.rules_replace)
            + len(self.rules_remove)
        )


def _shop_rules(retailer: Retailer) -> list[DiscountRule]:
    return list(
        DiscountRule.objects.filter(audience_type=DiscountRule.Audience.RETAILER, retailer=retailer)
        .select_related("product")
        .prefetch_related("slabs")
        .order_by("created_at", "pk")
    )


def _specials(retailer: Retailer) -> dict[UUID, RetailerPrice]:
    rows = RetailerPrice.objects.filter(retailer=retailer).select_related("product")
    return {row.product_id: row for row in rows}


def plan_copy(source: Retailer, target: Retailer, mode: str) -> CopyPlan:
    if mode not in CopyMode.values:
        raise InvalidFields({"mode": [gettext("Choose “Replace” or “Add”.")]})
    if source.pk == target.pk:
        raise InvalidFields({"copy_from": [gettext("Choose a different shop to copy from.")]})
    plan = CopyPlan()
    if source.price_list_id != target.price_list_id:
        plan.price_list = (
            target.price_list.name if target.price_list else None,
            source.price_list.name if source.price_list else None,
        )
    theirs, mine = _specials(source), _specials(target)
    for product_id, row in theirs.items():
        have = mine.get(product_id)
        if have is None:
            plan.prices_add.append((row.product.code, row.product.name, row.price))
        elif have.price != row.price:
            plan.prices_update.append((row.product.code, row.product.name, have.price, row.price))
    if mode == CopyMode.REPLACE:
        plan.prices_remove = [
            (row.product.code, row.product.name, row.price)
            for product_id, row in mine.items()
            if product_id not in theirs
        ]
    source_rules, target_rules = _shop_rules(source), _shop_rules(target)
    target_simple = {r.product_id: r for r in target_rules if is_simple(r)}
    for rule in source_rules:
        if mode == CopyMode.ADD and is_simple(rule) and rule.product_id in target_simple:
            plan.rules_replace.append(_copied_name(rule, source, target))
        else:
            plan.rules_add.append(_copied_name(rule, source, target))
    if mode == CopyMode.REPLACE:
        plan.rules_remove = [r.name for r in target_rules]
    return plan


def _copied_name(rule: DiscountRule, source: Retailer, target: Retailer) -> str:
    if source.code in rule.name:
        return rule.name.replace(source.code, target.code)
    return f"{rule.name} ({target.code})"[:120]


@transaction.atomic
def copy_pricing(
    source_id: UUID, target_id: UUID, mode: str, *, expected_changes: int, by: User
) -> CopyPlan:
    target = Retailer.objects.select_for_update().filter(pk=target_id).first()
    source = Retailer.objects.filter(pk=source_id, deleted_at__isnull=True).first()
    if target is None:
        raise NotFound()
    if source is None:
        raise InvalidFields({"copy_from": [gettext("Choose an existing shop.")]})
    plan = plan_copy(source, target, mode)
    if plan.changes != expected_changes:
        raise PreviewOutOfDate(
            gettext("The pricing of one of these shops has changed. Preview it again.")
        )
    if plan.price_list:
        services.assign_price_list(target, source.price_list_id)
        target.price_list_id = source.price_list_id
        target.save(update_fields=["price_list", "updated_at"])
    theirs, mine = _specials(source), _specials(target)
    if mode == CopyMode.REPLACE:
        RetailerPrice.objects.filter(retailer=target).exclude(product_id__in=list(theirs)).delete()
        DiscountRule.objects.filter(
            audience_type=DiscountRule.Audience.RETAILER, retailer=target
        ).delete()
    for product_id, row in theirs.items():
        have = mine.get(product_id)
        if have is None:
            RetailerPrice.objects.create(
                retailer=target,
                product_id=product_id,
                price=row.price,
                note=row.note,
                created_by=by,
            )
        elif have.price != row.price:
            have.price, have.note = row.price, row.note
            have.save(update_fields=["price", "note", "updated_at"])
    target_simple = {
        r.product_id: r for r in _shop_rules(target) if is_simple(r)
    }  # empty after REPLACE
    for rule in _shop_rules(source):
        existing = target_simple.get(rule.product_id) if is_simple(rule) else None
        if existing is not None:
            existing.discount_type, existing.value, existing.is_active = (
                rule.discount_type,
                rule.value,
                rule.is_active,
            )
            existing.save(update_fields=["discount_type", "value", "is_active", "updated_at"])
            continue
        slabs = list(rule.slabs.all())
        copy = DiscountRule.objects.create(
            name=_copied_name(rule, source, target),
            discount_type=rule.discount_type,
            value=rule.value,
            scope_type=rule.scope_type,
            product_id=rule.product_id,
            category_id=rule.category_id,
            brand_id=rule.brand_id,
            audience_type=DiscountRule.Audience.RETAILER,
            retailer=target,
            valid_from=rule.valid_from,
            valid_to=rule.valid_to,
            is_active=rule.is_active,
            created_by=by,
        )
        DiscountSlab.objects.bulk_create(
            [
                DiscountSlab(tenant_id=copy.tenant_id, rule=copy, min_qty=s.min_qty, value=s.value)
                for s in slabs
            ]
        )
    audit.record(
        "pricing.pricing_copied",
        target=target,
        target_repr=f"{target.code} {target.shop_name}",
        metadata={
            "from": f"{source.code} {source.shop_name}",
            "mode": mode,
            "price_list": list(plan.price_list) if plan.price_list else None,
            "special_prices": {
                "added": len(plan.prices_add),
                "changed": len(plan.prices_update),
                "removed": len(plan.prices_remove),
            },
            "rules": {
                "added": len(plan.rules_add),
                "replaced": len(plan.rules_replace),
                "removed": len(plan.rules_remove),
            },
        },
    )
    return plan


# --- Bulk percentage change to a price list -----------------------------------------------------


@dataclass(frozen=True)
class AdjustRow:
    product_id: UUID
    code: str
    name: str
    old: Decimal | None  # None: not on the list yet (added from the standard price)
    new: Decimal


@dataclass(frozen=True)
class Adjustment:
    percent: Decimal
    category_id: UUID | None = None
    brand_id: UUID | None = None
    include_missing: bool = False
    whole_rupees: bool = False


def _check_adjustment(a: Adjustment) -> None:
    errors: dict[str, list[str]] = {}
    if (a.category_id is None) == (a.brand_id is None):
        errors["scope"] = [gettext("Choose a category or a brand.")]
    if a.category_id and catalog.category(a.category_id) is None:
        errors["category"] = [gettext("Choose an existing category.")]
    if a.brand_id and not Brand.objects.filter(pk=a.brand_id, deleted_at__isnull=True).exists():
        errors["brand"] = [gettext("Choose an existing brand.")]
    if not Decimal("-99.99") <= a.percent <= Decimal("1000") or a.percent == 0:
        errors["percent"] = [gettext("Enter a change between -99.99% and +1000%, other than 0.")]
    if errors:
        raise InvalidFields(errors)


def plan_adjustment(price_list: PriceList, a: Adjustment) -> list[AdjustRow]:
    """The list prices that would change (ADR-037 item 4); rounding via ``billing.tax``."""
    _check_adjustment(a)
    scope = catalog.products(
        catalog.ProductFilters(category_id=a.category_id, brand_id=a.brand_id, is_active=True)
    ).order_by("code")
    listed = dict(
        PriceListItem.objects.filter(price_list=price_list, product__in=scope).values_list(
            "product_id", "price"
        )
    )
    rows: list[AdjustRow] = []
    for product in scope:
        old = listed.get(product.pk)
        if old is None and not a.include_missing:
            continue
        start = old if old is not None else product.base_price
        new = adjust_price(start, a.percent, whole_rupees=a.whole_rupees)
        if new != old:
            rows.append(AdjustRow(product.pk, product.code, product.name, old, new))
    return rows


@transaction.atomic
def adjust_price_list(
    price_list_id: UUID, a: Adjustment, *, expected_count: int, by: User
) -> tuple[list[AdjustRow], list[Warning]]:
    price_list = (
        PriceList.objects.select_for_update()
        .filter(pk=price_list_id, deleted_at__isnull=True)
        .first()
    )
    if price_list is None:
        raise NotFound()
    rows = plan_adjustment(price_list, a)
    if len(rows) != expected_count:
        raise PreviewOutOfDate(gettext("The prices on this list have changed. Preview it again."))
    warnings: list[Warning] = []
    for start in range(0, len(rows), services.MAX_BULK_ITEMS):
        chunk = rows[start : start + services.MAX_BULK_ITEMS]
        _, found = services.upsert_items(
            price_list.pk, [services.ItemInput(r.product_id, r.new) for r in chunk], by=by
        )
        warnings = warnings or found
    target = Category.objects.filter(pk=a.category_id).first() if a.category_id else None
    brand = Brand.objects.filter(pk=a.brand_id).first() if a.brand_id else None
    audit.record(
        "pricing.price_list_adjusted",
        target=price_list,
        target_repr=price_list.name,
        metadata={
            "percent": f"{a.percent.normalize():f}",
            "category": target.name if target else None,
            "brand": brand.name if brand else None,
            "include_missing": a.include_missing,
            "rounding": "RUPEE" if a.whole_rupees else "PAISA",
            "count": len(rows),
        },
    )
    return rows, warnings


# --- Shop pricing report ------------------------------------------------------------------------


def shop_pricing_report(
    shops: QuerySet[Retailer], *, customised_only: bool = True
) -> QuerySet[Retailer]:
    """Shops with their counts of special prices and shop-specific discount rules."""
    specials = (
        RetailerPrice.objects.filter(retailer=OuterRef("pk"))
        .values("retailer")
        .annotate(n=Count("pk"))
        .values("n")
    )
    rules = (
        DiscountRule.objects.filter(
            audience_type=DiscountRule.Audience.RETAILER, retailer=OuterRef("pk")
        )
        .values("retailer")
        .annotate(n=Count("pk"))
        .values("n")
    )
    qs = shops.annotate(
        special_price_count=Coalesce(Subquery(specials), 0),
        shop_rule_count=Coalesce(Subquery(rules), 0),
    )
    if customised_only:
        qs = qs.filter(Q(special_price_count__gt=0) | Q(shop_rule_count__gt=0))
    return qs


def free_products(retailer: Retailer) -> list[Product]:
    """Products this shop gets free today: a ₹0 special or list price, or discounts reaching the
    whole price at some quantity (ADR-038 item 6). Only products whose rules could add up to the
    whole price are priced in full."""
    products = list(
        sellable_products()
        .filter(show_in_shop=True)
        .select_related(None)
        .only(
            "pk",
            "code",
            "name",
            "category_id",
            "brand_id",
            "base_price",
            "min_order_qty",
            "is_active",
            "deleted_at",
            "tenant_id",
        )
    )
    return resolve.free_among(retailer, products)


def report_row_extra(retailer: Retailer) -> dict[str, Any]:
    return {"free_product_count": len(free_products(retailer))}
