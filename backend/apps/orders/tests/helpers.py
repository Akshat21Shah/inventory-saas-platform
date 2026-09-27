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
