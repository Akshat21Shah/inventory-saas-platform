"""Pricing reads."""

from uuid import UUID

from django.db.models import Count, IntegerField, OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce

from apps.accounts.models import User
from apps.pricing.models import DiscountRule, PriceList, PriceListItem, RetailerPrice
from apps.retailers.models import Retailer
from apps.retailers.selectors import retailers_for


def price_lists() -> QuerySet[PriceList]:
    shops = (
        Retailer.objects.filter(price_list=OuterRef("pk"), deleted_at__isnull=True)
        .order_by()
        .values("price_list")
        .annotate(n=Count("pk"))
        .values("n")
    )
    lists: QuerySet[PriceList] = PriceList.objects.filter(deleted_at__isnull=True).annotate(
        item_count=Count("items", distinct=True),
        shop_count=Coalesce(Subquery(shops, output_field=IntegerField()), 0),
    )
    return lists


def price_list(price_list_id: UUID) -> PriceList | None:
    found: PriceList | None = price_lists().filter(pk=price_list_id).first()
    return found


def price_list_items(price_list_id: UUID, search: str = "") -> QuerySet[PriceListItem]:
    qs = PriceListItem.objects.filter(
        price_list_id=price_list_id, product__deleted_at__isnull=True
    ).select_related("product", "product__unit")
    term = search.strip()
    if term:
        qs = qs.filter(Q(product__code__icontains=term) | Q(product__name__icontains=term))
    return qs


def retailer_prices(
    user: User, *, retailer_id: UUID | None = None, product_id: UUID | None = None
) -> QuerySet[RetailerPrice]:
    """Special prices of the shops this user can see (sales staff may see only theirs)."""
    qs = RetailerPrice.objects.filter(
        retailer__in=retailers_for(user), product__deleted_at__isnull=True
    ).select_related("retailer", "product")
    if retailer_id:
        qs = qs.filter(retailer_id=retailer_id)
    if product_id:
        qs = qs.filter(product_id=product_id)
    return qs


def discount_rules(*, active: bool | None = None) -> QuerySet[DiscountRule]:
    qs = DiscountRule.objects.select_related(
        "product", "category", "brand", "price_list", "retailer"
    ).prefetch_related("slabs")
    return qs if active is None else qs.filter(is_active=active)
