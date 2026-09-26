"""``resolve_price``: the only place a retailer's price is decided (spec 5.6, PLAN M1-M6, ADR-036).

1. Unit price = the retailer's special price → the retailer's price list → the product base price.
2. Discount = the applicable active rules, combined as ⚙ ``pricing.discount_combination`` says
   (ADR-038). Line math comes from ``billing.tax``; the total never exceeds the line gross.
   - ``BEST``: the single rule with the largest amount; ties go to the most specific audience
     (shop > price list > everyone), then scope (product > deeper category > brand > all
     products), then the newest rule.
   - ``ADD``: every rule's amount on the original line, added up.
   - ``SEQUENTIAL``: most specific rule first (audience, scope, newest), each on what is left.
   A category rule covers its sub-categories. A rule with slabs uses the slab with the highest
   minimum quantity not above the line quantity; if none is reached the rule doesn't apply.
   ⚙ ``pricing.discounts_on_special_prices`` = false makes a special price final.
3. The result carries every rule applied, the total and the order line snapshot (Phase 4).

Prices are in the tenant's price basis (⚙ ``tax.prices_include_gst``); the flag is returned.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import Q
from django.utils import timezone

from apps.billing.tax import (
    ComponentRounding,
    Discount,
    DiscountType,
    line_discount,
    line_gross,
    percent_of,
)
from apps.catalog import selectors as catalog
from apps.catalog.models import Category, Product
from apps.platform.selectors import get_setting
from apps.pricing.models import DiscountRule, DiscountSlab, PriceListItem, RetailerPrice
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.error_codes import ErrorCode
from common.errors import DomainError
from common.ids import uuid7

PAISA = Decimal("0.01")
ZERO = Decimal("0")


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
    discounts: tuple[AppliedDiscount, ...]  # every rule applied, in the order applied
    discount_total: Decimal  # for the line; never more than the gross
    discount_percent: Decimal  # of the gross, to two decimals (what the shop sees)
    gross: Decimal  # qty * unit price, rounded to paise
    line_net: Decimal  # gross - discount_total
    net_unit_price: Decimal  # informational only (PLAN M1)
    gst_rate: Decimal
    cess_rate: Decimal
    prices_include_gst: bool
    on: date

    @property
    def discount_per_unit(self) -> Decimal:
        """Unit price minus net unit price (informational, like ``net_unit_price``)."""
        return self.unit_price - self.net_unit_price

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
    # category id -> (parent id, level); loaded once, only when a category rule exists
    categories: dict[UUID, tuple[UUID | None, int]] = field(default_factory=dict)
    discounts_on_special: bool = True
    combination: str = "BEST"
    include_gst: bool = False
    rounding: ComponentRounding = ComponentRounding.HALF_UP


_AUDIENCE_RANK = {"RETAILER": 3, "PRICE_LIST": 2, "ALL": 1}


def _slabs(rule: DiscountRule) -> list[Any]:
    return list(rule.slabs.all())


def _active_rules(retailer: Retailer, on: date) -> list[DiscountRule]:
    audience = Q(audience_type="ALL") | Q(audience_type="RETAILER", retailer=retailer)
    if retailer.price_list_id:
        audience |= Q(audience_type="PRICE_LIST", price_list_id=retailer.price_list_id)
    return list(
        DiscountRule.objects.filter(audience, is_active=True)
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=on))
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=on))
        .prefetch_related("slabs")
    )


def _category_chain(category_id: UUID | None, ctx: _Context) -> list[tuple[UUID, int]]:
    """The product's category and its ancestors as (id, level) (a category rule covers
    descendants)."""
    chain: list[tuple[UUID, int]] = []
    current = category_id
    while current is not None and current in ctx.categories and len(chain) < 3:
        parent, level = ctx.categories[current]
        chain.append((current, level))
        current = parent
    return chain


def _scope_rank(rule: DiscountRule, product: Product, chain: list[tuple[UUID, int]]) -> int | None:
    """How specific a matching rule's scope is; None if it doesn't cover the product."""
    if rule.scope_type == "ALL":
        return 0
    if rule.scope_type == "PRODUCT":
        return 20 if rule.product_id == product.pk else None
    if rule.scope_type == "BRAND":
        return 5 if product.brand_id and rule.brand_id == product.brand_id else None
    for category_id, level in chain:
        if category_id == rule.category_id:
            return 10 + level  # deeper category = more specific
    return None


def _rule_value(rule: DiscountRule, qty: Decimal) -> tuple[Decimal, Decimal | None] | None:
    slabs = _slabs(rule)
    if not slabs:
        return (rule.value, None) if rule.value > 0 else None
    reached = [s for s in slabs if s.min_qty <= qty]
    if not reached:
        return None
    best = max(reached, key=lambda s: s.min_qty)
    return best.value, best.min_qty


@dataclass(frozen=True)
class _Candidate:
    rule: DiscountRule
    value: Decimal
    slab: Decimal | None
    specificity: tuple[Any, ...]  # (audience, scope, created, id): larger is more specific


def _candidates(product: Product, qty: Decimal, ctx: _Context) -> list[_Candidate]:
    chain = _category_chain(product.category_id, ctx)
    found: list[_Candidate] = []
    for rule in ctx.rules:
        scope = _scope_rank(rule, product, chain)
        if scope is None:
            continue
        picked = _rule_value(rule, qty)
        if picked is None:
            continue
        value, slab = picked
        specificity = (_AUDIENCE_RANK[rule.audience_type], scope, rule.created_at, str(rule.pk))
        found.append(_Candidate(rule, value, slab, specificity))
    return found


def _applied(candidate: _Candidate, amount: Decimal) -> AppliedDiscount:
    return AppliedDiscount(
        rule_id=candidate.rule.pk,
        rule_name=candidate.rule.name,
        discount_type=candidate.rule.discount_type,
        value=candidate.value,
        slab_min_qty=candidate.slab,
        amount=amount,
    )


def _discounts(
    product: Product, qty: Decimal, gross: Decimal, ctx: _Context
) -> list[AppliedDiscount]:
    """The rules applied to one line, combined as the tenant's setting says (ADR-038)."""
    candidates = _candidates(product, qty, ctx)
    if not candidates or gross <= 0:
        return []

    def amount_on(base: Decimal, c: _Candidate) -> Decimal:
        discount = Discount(DiscountType(c.rule.discount_type), c.value)
        return min(line_discount(base, qty, discount, ctx.rounding), base)

    if ctx.combination == "BEST":
        best = max(candidates, key=lambda c: (amount_on(gross, c), *c.specificity))
        amount = amount_on(gross, best)
        return [_applied(best, amount)] if amount > 0 else []
    applied: list[AppliedDiscount] = []
    remaining = gross
    for c in sorted(candidates, key=lambda c: c.specificity, reverse=True):
        if remaining <= 0:
            break
        # ADD: each on the original line; SEQUENTIAL: each on what is left. Both stop at the gross.
        amount = min(amount_on(gross if ctx.combination == "ADD" else remaining, c), remaining)
        if amount > 0:
            applied.append(_applied(c, amount))
            remaining -= amount
    return applied


def _context(
    retailer: Retailer,
    on: date,
    *,
    extra_rules: Iterable[DiscountRule] = (),
    exclude_rule_ids: Iterable[UUID] = (),
) -> _Context:
    tenant_id = retailer.tenant_id
    excluded = set(exclude_rule_ids)
    rules = [r for r in _active_rules(retailer, on) if r.pk not in excluded] + list(extra_rules)
    categories: dict[UUID, tuple[UUID | None, int]] = {}
    if any(rule.scope_type == "CATEGORY" for rule in rules):
        categories = {
            pk: (parent, level)
            for pk, parent, level in Category.objects.values_list("pk", "parent_id", "level")
        }
    return _Context(
        retailer=retailer,
        on=on,
        rules=rules,
        categories=categories,
        discounts_on_special=bool(get_setting("pricing.discounts_on_special_prices", tenant_id)),
        combination=str(get_setting("pricing.discount_combination", tenant_id)),
        include_gst=bool(get_setting("tax.prices_include_gst", tenant_id)),
        rounding=ComponentRounding(get_setting("tax.component_rounding", tenant_id)),
    )


def hypothetical_rule(**fields: Any) -> DiscountRule:
    """An unsaved rule for "what if" previews (the discount grid): no slabs, never queried."""
    rule = DiscountRule(pk=uuid7(), created_at=timezone.now(), is_active=True, **fields)
    rule._prefetched_objects_cache = {"slabs": DiscountSlab.objects.none()}  # type: ignore[attr-defined]
    return rule


def resolve_prices(
    retailer: Retailer,
    lines: Iterable[tuple[Product, Decimal]],
    *,
    on: date | None = None,
    extra_rules: Iterable[DiscountRule] = (),
    exclude_rule_ids: Iterable[UUID] = (),
) -> list[PriceResult]:
    """``resolve_price`` for many lines at once (catalog pages, carts): one query per source.
    ``extra_rules`` / ``exclude_rule_ids`` answer "what if" questions without saving anything."""
    day = on or today_ist()
    lines = list(lines)
    ctx = _context(retailer, day, extra_rules=extra_rules, exclude_rule_ids=exclude_rule_ids)
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
        discounts: list[AppliedDiscount] = []
        if source != "SPECIAL" or ctx.discounts_on_special:
            discounts = _discounts(product, qty, gross, ctx)
        total = sum((d.amount for d in discounts), Decimal("0.00"))
        net = gross - total
        rate = rates[product.pk]
        results.append(
            PriceResult(
                product_id=product.pk,
                qty=qty,
                base_price=product.base_price,
                unit_price=unit,
                price_source=source,
                discounts=tuple(discounts),
                discount_total=total,
                discount_percent=percent_of(total, gross, ctx.rounding),
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


def slab_quantities(
    retailer: Retailer, product: Product, *, on: date | None = None
) -> list[Decimal]:
    """The slab thresholds of the active rules covering this product for this shop, ascending
    (for "buy 24+ and pay less" hints; ``resolve_prices`` still decides the price at each)."""
    ctx = _context(retailer, on or today_ist())
    chain = _category_chain(product.category_id, ctx)
    found = {
        slab.min_qty
        for rule in ctx.rules
        if _scope_rank(rule, product, chain) is not None
        for slab in rule.slabs.all()
    }
    return sorted(found)


def free_among(retailer: Retailer, products: list[Product]) -> list[Product]:
    """Which of ``products`` this shop gets free today: a ₹0 special or list price, or discounts
    that reach the whole price at the highest slab quantity. A cheap upper bound (each rule's
    largest % or flat share, the best one or the sum as the setting says) picks the products that
    are then priced in full (ADR-038 item 6)."""
    day = today_ist()
    ctx = _context(retailer, day)
    ids = [p.pk for p in products]
    special = dict(
        RetailerPrice.objects.filter(retailer=retailer, product_id__in=ids).values_list(
            "product_id", "price"
        )
    )
    listed: dict[UUID, Decimal] = {}
    if retailer.price_list_id:
        listed = dict(
            PriceListItem.objects.filter(
                price_list_id=retailer.price_list_id,
                product_id__in=ids,
                price_list__deleted_at__isnull=True,
            ).values_list("product_id", "price")
        )
    free: list[Product] = []
    at_risk: list[tuple[Product, Decimal]] = []
    for product in products:
        if product.pk in special:
            unit, source = special[product.pk], "SPECIAL"
        elif product.pk in listed:
            unit, source = listed[product.pk], "PRICE_LIST"
        else:
            unit, source = product.base_price, "BASE"
        if unit <= 0:
            if source != "BASE":  # a ₹0 price someone set, not a product without a price
                free.append(product)
            continue
        if source == "SPECIAL" and not ctx.discounts_on_special:
            continue
        chain = _category_chain(product.category_id, ctx)
        shares: list[Decimal] = []
        qty = product.min_order_qty
        for rule in ctx.rules:
            if _scope_rank(rule, product, chain) is None:
                continue
            slabs = _slabs(rule)
            value = max(s.value for s in slabs) if slabs else rule.value
            if slabs:
                qty = max(qty, max(s.min_qty for s in slabs))
            share = value if rule.discount_type == "PERCENT" else value * 100 / unit
            shares.append(share)
        bound = (max(shares) if ctx.combination == "BEST" else sum(shares)) if shares else ZERO
        if bound >= 100:
            at_risk.append((product, qty))
    if at_risk:
        results = resolve_prices(retailer, at_risk, on=day)
        free.extend(p for (p, _), r in zip(at_risk, results, strict=True) if r.line_net <= 0)
    return free
