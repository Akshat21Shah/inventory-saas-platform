"""Shared helpers for order tests: shops with sign-ins, stock, and API clients."""

from decimal import Decimal
from typing import Any
from uuid import uuid4

from django.db import transaction
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.tests.factories import make_staff_in
from apps.accounts.tokens import issue_tokens
from apps.inventory import services as stock
from apps.platform.services import set_tenant_settings
from apps.retailers.models import Retailer, RetailerAddress
from apps.retailers.services import AddressInput, create_retailer
from common.tenancy import tenant_context

D = Decimal


def make_shop(tenant: Any, phone: str = "9876500051", **extra: Any) -> Retailer:
    with tenant_context(tenant.pk):
        shop = create_retailer(
            shop_name=extra.pop("shop_name", f"Shop {phone[-3:]}"),
            phone=phone,
            send_welcome=False,
            billing=AddressInput("12 Market Road", "Pune", "411001", "27"),
            **extra,
        )
        return shop


def shop_user(shop: Retailer) -> User:
    user: User = User.objects.get(tenant=shop.tenant_id, phone=shop.mobile)
    return user


def client_for(tenant: Any, user: User) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, tenant.pk).access}")
    client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant.slug}.localhost"
    return client


def shop_client(tenant: Any, shop: Retailer) -> APIClient:
    return client_for(tenant, shop_user(shop))


def staff_client(tenant: Any, role: str = "OWNER") -> APIClient:
    return client_for(tenant, make_staff_in(tenant, role))


def add_stock(tenant: Any, product: Any, qty: str) -> None:
    with tenant_context(tenant.pk), transaction.atomic():
        level = stock.lock_levels([product.pk], stock.default_warehouse())[product.pk]
        stock.add(level, D(qty), stock.Ref("ADJUSTMENT", uuid4()), by=None)


def settings(tenant: Any, **values: Any) -> None:
    from django.core.cache import cache

    with tenant_context(tenant.pk):
        set_tenant_settings({k.replace("__", "."): v for k, v in values.items()}, user=None)
    cache.clear()


def add_address(
    tenant: Any, shop: Retailer, state: str, *, default: bool = True
) -> RetailerAddress:
    with tenant_context(tenant.pk):
        address: RetailerAddress = RetailerAddress.objects.create(
            retailer=shop,
            kind="SHIPPING",
            label="Godown",
            line1="Plot 4",
            city="Surat",
            pincode="395003",
            state_id=state,
            is_default=default,
        )
        return address


def place(
    tenant: Any,
    shop: Retailer,
    *lines: tuple[Any, str],
    via: str = "RETAILER_APP",
    by: User | None = None,
) -> Any:
    """Place an order directly through the service (no cart), at the current prices."""
    from apps.inventory.availability import ShopStockRules
    from apps.orders.cart import live_rules
    from apps.orders.quote import build_quote
    from apps.orders.services import Placement, place_order

    items = [(product.pk, D(qty)) for product, qty in lines]
    with tenant_context(tenant.pk):
        quote = build_quote(
            shop,
            items,
            rules=live_rules(tenant.pk),
            stock_rules=ShopStockRules.for_tenant(tenant.pk),
        )
        return place_order(
            Placement(
                retailer=shop,
                placed_by=by or shop_user(shop),
                via=via,
                items=items,
                expected_total=quote.totals.grand_total,
            )
        )


def check_order_invariants(tenant: Any) -> None:
    """Stock agrees with its movements, and with the orders (PLAN §5.5): what is reserved is what
    order lines hold plus what shipments hold until dispatch; backorder demand is what lines
    wait for."""
    from django.db.models import F, Sum

    from apps.inventory.models import StockLevel
    from apps.inventory.tests.helpers import check_invariants
    from apps.orders.models import OrderLine

    check_invariants(tenant)
    with tenant_context(tenant.pk):
        for level in StockLevel.objects.all():
            held = OrderLine.objects.filter(product_id=level.product_id).aggregate(
                reserved=Sum(F("qty_reserved") + F("qty_allocated") - F("qty_dispatched")),
                waiting=Sum("qty_backordered"),
            )
            assert level.quantity_reserved == (held["reserved"] or 0), level.product_id
            assert level.quantity_backordered == (held["waiting"] or 0), level.product_id
