"""``resolve_price``: the only place a retailer's price is decided (spec 5.6, PLAN M1-M6, ADR-036).

1. Unit price = the retailer's special price → the retailer's price list → the product base price.
2. Discount = the single best applicable active rule (no stacking in v1):
   - highest discount amount on the line (line math from ``billing.tax``), then
   - the most specific audience (shop > price list > everyone), then
   - the most specific scope (product > deeper category > brand > all products), then
   - the newest rule.
   A category rule covers its sub-categories. A rule with slabs uses the slab with the highest
   minimum quantity not above the line quantity; if none is reached the rule doesn't apply.
   ⚙ ``pricing.discounts_on_special_prices`` = false makes a special price final.
3. The result carries everything the order line will snapshot (Phase 4).

Prices are in the tenant's price basis (⚙ ``tax.prices_include_gst``); the flag is returned.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import Q

from apps.billing.tax import ComponentRounding, Discount, DiscountType, line_discount, line_gross
from apps.catalog import selectors as catalog
from apps.catalog.models import Category, Product
from apps.platform.selectors import get_setting
from apps.pricing.models import DiscountRule, PriceListItem, RetailerPrice
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.error_codes import ErrorCode
from common.errors import DomainError

PAISA = Decimal("0.01")


class PriceUnavailable(DomainError):
    status_code = 409
    code = ErrorCode.PRICE_UNAVAILABLE
    default_message = "This product can't be sold right now."


@dataclass(frozen=True)
class AppliedDiscount:
    rule_id: UUID
    rule_name: str
    discount_type: str
    value: Decimal  # the percentage or rupees per unit that applied
    slab_min_qty: Decimal | None
    amount: Decimal  # for the whole line


@dataclass(frozen=True)
class PriceResult:
    product_id: UUID
    qty: Decimal
    base_price: Decimal
    unit_price: Decimal
    price_source: str  # SPECIAL, PRICE_LIST or BASE
    discount: AppliedDiscount | None
    gross: Decimal  # qty * unit price, rounded to paise
    line_net: Decimal  # gross - discount
    net_unit_price: Decimal  # informational only (PLAN M1)
    gst_rate: Decimal
    cess_rate: Decimal
    prices_include_gst: bool
    on: date

    @property
    def valid(self) -> bool:
        """A shop sees a product only with a real price (ADR-034)."""
        return self.net_unit_price > 0


@dataclass
class _Context:
    """What resolving many products for one shop needs, loaded once."""

    retailer: Retailer
    on: date
    rules: list[DiscountRule]
    ancestors: dict[UUID, list[Category]] = field(default_factory=dict)
    discounts_on_special: bool = True
    include_gst: bool = False
    rounding: ComponentRounding = ComponentRounding.HALF_UP


_AUDIENCE_RANK = {"RETAILER": 3, "PRICE_LIST": 2, "ALL": 1}


def _active_rules(retailer: Retailer, on: date) -> list[DiscountRule]:
    audience = Q(audience_type="ALL") | Q(audience_type="RETAILER", retailer=retailer)
    if retailer.price_list_id:
        audience |= Q(audience_type="PRICE_LIST", price_list_id=retailer.price_list_id)
    return list(
        DiscountRule.objects.filter(audience, is_active=True)
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=on))
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=on))
        .prefetch_related("slabs")
        .select_related("category")
    )


def _category_chain(category_id: UUID | None, ctx: _Context) -> list[Category]:
    """The product's category and its ancestors (a category rule covers descendants)."""
    if category_id is None:
        return []
    if category_id not in ctx.ancestors:
        chain: list[Category] = []
        current = Category.objects.filter(pk=category_id).first()
        while current is not None:
            chain.append(current)
            current = current.parent if current.parent_id else None
        ctx.ancestors[category_id] = chain
    return ctx.ancestors[category_id]


def _scope_rank(rule: DiscountRule, product: Product, chain: list[Category]) -> int | None:
    """How specific a matching rule's scope is; None if it doesn't cover the product."""
    if rule.scope_type == "ALL":
        return 0
    if rule.scope_type == "PRODUCT":
        return 20 if rule.product_id == product.pk else None
    if rule.scope_type == "BRAND":
        return 5 if product.brand_id and rule.brand_id == product.brand_id else None
    for category in chain:
        if category.pk == rule.category_id:
            return 10 + category.level  # deeper category = more specific
    return None


def _rule_value(rule: DiscountRule, qty: Decimal) -> tuple[Decimal, Decimal | None] | None:
    slabs = list(rule.slabs.all())
    if not slabs:
        return (rule.value, None) if rule.value > 0 else None
    reached = [s for s in slabs if s.min_qty <= qty]
    if not reached:
        return None
    best = max(reached, key=lambda s: s.min_qty)
    return best.value, best.min_qty


def _best_discount(
    product: Product, qty: Decimal, gross: Decimal, ctx: _Context
) -> AppliedDiscount | None:
    chain = _category_chain(product.category_id, ctx)
    candidates: list[tuple[tuple[Any, ...], AppliedDiscount]] = []
    for rule in ctx.rules:
        scope = _scope_rank(rule, product, chain)
        if scope is None:
            continue
        picked = _rule_value(rule, qty)
        if picked is None:
            continue
        value, slab = picked
        amount = line_discount(
            gross, qty, Discount(DiscountType(rule.discount_type), value), ctx.rounding
        )
        if amount <= 0:
            continue
        applied = AppliedDiscount(
            rule_id=rule.pk,
            rule_name=rule.name,
            discount_type=rule.discount_type,
            value=value,
            slab_min_qty=slab,
            amount=amount,
        )
        key = (amount, _AUDIENCE_RANK[rule.audience_type], scope, rule.created_at, rule.pk)
        candidates.append((key, applied))
    if not candidates:
        return None
    return max(candidates, key=lambda c: c[0])[1]


def _context(retailer: Retailer, on: date) -> _Context:
    tenant_id = retailer.tenant_id
    return _Context(
        retailer=retailer,
        on=on,
        rules=_active_rules(retailer, on),
        discounts_on_special=bool(get_setting("pricing.discounts_on_special_prices", tenant_id)),
        include_gst=bool(get_setting("tax.prices_include_gst", tenant_id)),
        rounding=ComponentRounding(get_setting("tax.component_rounding", tenant_id)),
    )


def resolve_prices(
    retailer: Retailer, lines: Iterable[tuple[Product, Decimal]], *, on: date | None = None
) -> list[PriceResult]:
    """``resolve_price`` for many lines at once (catalog pages, carts): one query per source."""
    day = on or today_ist()
    lines = list(lines)
    ctx = _context(retailer, day)
    product_ids = [product.pk for product, _ in lines]
    special = dict(
        RetailerPrice.objects.filter(retailer=retailer, product_id__in=product_ids).values_list(
            "product_id", "price"
        )
    )
    listed: dict[UUID, Decimal] = {}
    if retailer.price_list_id:
        listed = dict(
            PriceListItem.objects.filter(
                price_list_id=retailer.price_list_id,
                product_id__in=product_ids,
                price_list__deleted_at__isnull=True,
            ).values_list("product_id", "price")
        )
    rates = catalog.tax_rates_on(product_ids, day)
    results: list[PriceResult] = []
    for product, qty in lines:
        if not product.is_active or product.deleted_at is not None or product.pk not in rates:
            raise PriceUnavailable(details={"product": str(product.pk)})
        if product.pk in special:
            unit, source = special[product.pk], "SPECIAL"
        elif product.pk in listed:
            unit, source = listed[product.pk], "PRICE_LIST"
        else:
            unit, source = product.base_price, "BASE"
        gross = line_gross(qty, unit, ctx.rounding)
        discount = None
        if source != "SPECIAL" or ctx.discounts_on_special:
            discount = _best_discount(product, qty, gross, ctx)
        net = gross - (discount.amount if discount else Decimal("0"))
        rate = rates[product.pk]
        results.append(
            PriceResult(
                product_id=product.pk,
                qty=qty,
                base_price=product.base_price,
                unit_price=unit,
                price_source=source,
                discount=discount,
                gross=gross,
                line_net=net,
                net_unit_price=(net / qty).quantize(PAISA) if qty else Decimal("0.00"),
                gst_rate=rate.gst_rate,
                cess_rate=rate.cess_rate,
                prices_include_gst=ctx.include_gst,
                on=day,
            )
        )
    return results


def resolve_price(
    retailer: Retailer, product: Product, qty: Decimal, *, on: date | None = None
) -> PriceResult:
    return resolve_prices(retailer, [(product, qty)], on=on)[0]
