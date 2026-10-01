"""Sales growth demo data (ADR-056, 9b.6): free-goods schemes and shop activity.

- Demo (``seed_demo_growth``): Sharma Distributors gets the ``free_goods`` module and three
  schemes (the same product, another product with a cap, one shop's own), shops that never
  ordered dated three weeks back so the win-back list has someone on it, one logged call, and the
  shop activity worked out. Patel Traders keeps the module off. Idempotent.
- Volume (``seed_volume_growth``): the module and a scheme per 25 products for the speed check,
  and the shop activity worked out over the year of orders. Left alone when schemes exist.

DEBUG only (called from the seed commands).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.insights import services as insights
from apps.insights.models import ShopContact
from apps.orders.models import Order
from apps.platform.models import FeatureFlag, Tenant, TenantFeature
from apps.platform.selectors import invalidate_tenant_features
from apps.pricing.models import FreeGoodsScheme
from apps.pricing.services import save_scheme
from apps.retailers.models import Retailer
from common.tenancy import tenant_context

DEMO_WITH_FREE_GOODS = ("sharma",)


@dataclass(frozen=True)
class Result:
    schemes: int
    shops: int


SCHEMES: list[tuple[str, str, str, str, str, dict[str, object]]] = [
    ("Rice: buy 12 get 1 free", "SH-0021", "12", "SH-0021", "1", {}),
    (
        "Shampoo with a free floor cleaner",
        "SH-0010",
        "6",
        "SH-0041",
        "1",
        {"max_free_qty": Decimal("5")},
    ),
    (
        "Ganesh Kirana: detergent 5 + 1",
        "SH-0040",
        "5",
        "SH-0040",
        "1",
        {"audience_type": "RETAILER"},
    ),
]
CODES = {code for _, buy, _, free, _, _ in SCHEMES for code in (buy, free)}


def _module_on(tenant: Tenant) -> None:
    TenantFeature.objects.update_or_create(
        flag=FeatureFlag.objects.get(code="free_goods"), defaults={"enabled": True}
    )
    invalidate_tenant_features(tenant.pk)


def seed_demo_growth(tenant: Tenant, owner: User) -> bool:
    """Inside ``tenant_context``; returns whether free goods are on for this distributor."""
    shops = Retailer.objects.filter(deleted_at__isnull=True)
    never = shops.exclude(pk__in=Order.objects.values("retailer_id"))
    never.filter(created_at__gt=timezone.now() - timedelta(days=15)).update(
        created_at=timezone.now() - timedelta(days=21)
    )
    first = shops.order_by("shop_name").first()
    if first is not None and not ShopContact.objects.exists():
        insights.log_contact(
            first.pk,
            channel=ShopContact.Channel.CALL,
            outcome=ShopContact.Outcome.WILL_ORDER,
            note="Will order after Diwali stock clears",
            by=owner,
        )
    insights.refresh_activity()
    if tenant.slug not in DEMO_WITH_FREE_GOODS:
        return False
    _module_on(tenant)
    if FreeGoodsScheme.objects.exists():
        return True
    products = {p.code: p for p in Product.objects.filter(code__in=CODES)}
    ganesh = shops.filter(shop_name="Ganesh Kirana").first()
    for name, buy, buy_qty, free, free_qty, extra in SCHEMES:
        if buy not in products or free not in products:
            continue
        if extra.get("audience_type") == "RETAILER":
            if ganesh is None:
                continue
            extra = {**extra, "retailer_id": ganesh.pk}
        save_scheme(
            None,
            {
                "name": name,
                "buy_product_id": products[buy].pk,
                "buy_qty": Decimal(buy_qty),
                "free_product_id": products[free].pk,
                "free_qty": Decimal(free_qty),
                "audience_type": "ALL",
                **extra,
            },
            by=owner,
        )
    return True


def seed_volume_growth(tenant: Tenant) -> Result | None:
    """Inside the caller's transaction; ``None`` when the distributor already has schemes."""
    with tenant_context(tenant.pk):
        if FreeGoodsScheme.objects.exists():
            return None
        _module_on(tenant)
        owner = User.objects.filter(email=f"owner@{tenant.slug}.example.com").first()
        products = list(Product.objects.filter(deleted_at__isnull=True).order_by("code")[::25])
        FreeGoodsScheme.objects.bulk_create(
            [
                FreeGoodsScheme(
                    tenant_id=tenant.pk,
                    name=f"{p.code}: buy 10 get 1",
                    buy_product=p,
                    buy_qty=Decimal("10"),
                    free_product=p,
                    free_qty=Decimal("1"),
                    audience_type="ALL",
                    created_by=owner,
                )
                for p in products
            ]
        )
        shops = insights.refresh_activity()
        return Result(len(products), shops)
