"""Free-goods warning (ADR-036): a discount rule, special price or price-list price that brings
a product's net price to zero for a shop hides that product from the shop (ADR-034). Saving it is
allowed, with a warning, because free-goods schemes ("buy X get Y free") aren't supported yet.

"Free" means the net price is zero at some quantity: a special price of 0, a percentage of 100 or
more, or rupees off per unit at or above the unit price. The rule's highest slab counts. Rules that
are switched off or have ended can't make anything free. Rules that start later still count.
"""

from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from django.db.models import Q, QuerySet

from apps.catalog import selectors as catalog
from apps.catalog.models import Product
from apps.catalog.services import Warning
from apps.platform.selectors import get_setting
from apps.pricing.models import DiscountRule, PriceList, PriceListItem, RetailerPrice
from apps.retailers.models import Retailer
from common.dates import today_ist

FREE_GOODS = "FREE_GOODS"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _warning(what: str, products: int, retailers: int) -> Warning:
    return Warning(
        FREE_GOODS,
        f"{what} makes {_plural(products, 'product')} free for {_plural(retailers, 'retailer')}. "
        "Free-goods schemes are not supported yet.",
        {"products": products, "retailers": retailers},
    )


def _highest_value(rule: DiscountRule) -> Decimal:
    slabs = [s.value for s in rule.slabs.all()]
    return max(slabs) if slabs else Decimal(rule.value or 0)


def _can_apply(rule: DiscountRule) -> bool:
    return rule.is_active and not (rule.valid_to and rule.valid_to < today_ist())


def _makes_free(kind: str, value: Decimal, unit_price: Decimal) -> bool:
    """``value`` is the rule's highest percentage or rupees off per unit."""
    if unit_price <= 0:
        return False  # already hidden without a price; not this rule's doing
    if kind == DiscountRule.Type.PERCENT:
        return value >= 100
    return value >= unit_price


def _products_in_scope(rule: DiscountRule) -> QuerySet[Product]:
    qs = Product.objects.filter(is_active=True, deleted_at__isnull=True, show_in_shop=True)
    if rule.scope_type == DiscountRule.Scope.PRODUCT:
        return qs.filter(pk=rule.product_id)
    if rule.scope_type == DiscountRule.Scope.CATEGORY:
        return qs.filter(category_id__in=catalog.descendant_ids(rule.category_id))  # type: ignore[arg-type]
    if rule.scope_type == DiscountRule.Scope.BRAND:
        return qs.filter(brand_id=rule.brand_id)
    return qs


def _retailers_in_audience(rule: DiscountRule) -> QuerySet[Retailer]:
    qs = Retailer.objects.filter(is_active=True, deleted_at__isnull=True)
    if rule.audience_type == DiscountRule.Audience.RETAILER:
        return qs.filter(pk=rule.retailer_id)
    if rule.audience_type == DiscountRule.Audience.PRICE_LIST:
        return qs.filter(price_list_id=rule.price_list_id)
    return qs


def rule_warnings(rule: DiscountRule) -> list[Warning]:
    """How many products this rule makes free, for how many shops (by each shop's unit price)."""
    if not _can_apply(rule):
        return []
    value = _highest_value(rule)
    if value <= 0 or (rule.discount_type == DiscountRule.Type.PERCENT and value < 100):
        return []
    products = _products_in_scope(rule)
    base = dict(products.values_list("pk", "base_price"))
    if not base:
        return []
    groups: dict[UUID | None, list[UUID]] = defaultdict(list)
    retailers = _retailers_in_audience(rule)
    for retailer_id, price_list_id in retailers.values_list("pk", "price_list_id"):
        groups[price_list_id].append(retailer_id)
    listed: dict[UUID, dict[UUID, Decimal]] = defaultdict(dict)
    for list_id, product_id, price in PriceListItem.objects.filter(
        price_list_id__in=[g for g in groups if g is not None],
        price_list__deleted_at__isnull=True,
        product_id__in=products.values("pk"),
    ).values_list("price_list_id", "product_id", "price"):
        listed[list_id][product_id] = price
    special: dict[UUID, dict[UUID, Decimal]] = defaultdict(dict)
    for retailer_id, product_id, price in RetailerPrice.objects.filter(
        retailer__in=retailers, product_id__in=products.values("pk")
    ).values_list("retailer_id", "product_id", "price"):
        special[retailer_id][product_id] = price
    on_special = bool(get_setting("pricing.discounts_on_special_prices", rule.tenant_id))

    free_products: set[UUID] = set()
    free_retailers = 0
    for list_id, retailer_ids in groups.items():
        prices = listed.get(list_id, {}) if list_id else {}
        group_free = {
            p for p, b in base.items() if _makes_free(rule.discount_type, value, prices.get(p, b))
        }
        for retailer_id in retailer_ids:
            own = special.get(retailer_id)
            mine = {p for p in group_free if not own or p not in own}
            if own and on_special:
                mine |= {
                    p for p, price in own.items() if _makes_free(rule.discount_type, value, price)
                }
            if mine:
                free_retailers += 1
                free_products |= mine
    if not free_products:
        return []
    return [_warning("This rule", len(free_products), free_retailers)]


def special_price_warnings(row: RetailerPrice) -> list[Warning]:
    """A special price of 0, or one that a discount rule for this shop brings to 0."""
    if row.price == 0:
        return [_warning("This special price", 1, 1)]
    if not get_setting("pricing.discounts_on_special_prices", row.tenant_id):
        return []
    retailer, product = row.retailer, row.product
    audience = Q(audience_type="ALL") | Q(audience_type="RETAILER", retailer_id=retailer.pk)
    if retailer.price_list_id:
        audience |= Q(audience_type="PRICE_LIST", price_list_id=retailer.price_list_id)
    scope = Q(scope_type="ALL") | Q(scope_type="PRODUCT", product_id=product.pk)
    if product.brand_id:
        scope |= Q(scope_type="BRAND", brand_id=product.brand_id)
    if product.category_id:
        chain = catalog.ancestor_ids(product.category_id)
        scope |= Q(scope_type="CATEGORY", category_id__in=chain)
    rules = DiscountRule.objects.filter(audience, scope).prefetch_related("slabs")
    if any(
        _can_apply(r) and _makes_free(r.discount_type, _highest_value(r), row.price) for r in rules
    ):
        return [_warning("This special price", 1, 1)]
    return []


def price_list_warnings(price_list: PriceList, product_ids: list[UUID]) -> list[Warning]:
    """₹0 list prices among ``product_ids``: free for the list's shops that have no special
    price for the product (a special price comes first)."""
    zero = set(
        PriceListItem.objects.filter(
            price_list=price_list,
            product_id__in=product_ids,
            price=0,
            product__is_active=True,
            product__deleted_at__isnull=True,
            product__show_in_shop=True,
        ).values_list("product_id", flat=True)
    )
    if not zero:
        return []
    shops = list(
        Retailer.objects.filter(
            price_list=price_list, is_active=True, deleted_at__isnull=True
        ).values_list("pk", flat=True)
    )
    special: dict[UUID, set[UUID]] = defaultdict(set)
    for retailer_id, product_id in RetailerPrice.objects.filter(
        retailer_id__in=shops, product_id__in=zero
    ).values_list("retailer_id", "product_id"):
        special[retailer_id].add(product_id)
    free_products: set[UUID] = set()
    free_shops = 0
    for shop in shops:
        mine = zero - special.get(shop, set())
        if mine:
            free_shops += 1
            free_products |= mine
    if not free_products:
        return []
    return [_warning("This price list", len(free_products), free_shops)]
