"""Shared helpers for inventory tests."""

from decimal import Decimal
from typing import Any

from apps.catalog.models import Product, ProductTaxRate, Unit
from apps.inventory import services
from common.dates import today_ist
from common.tenancy import tenant_context


def make_product(tenant: Any, code: str = "P-1", **extra: Any) -> Product:
    """A sellable product with its stock level (as ``create_product`` would make)."""
    with tenant_context(tenant.pk):
        fields: dict[str, Any] = {
            "code": code,
            "name": f"Product {code}",
            "unit": Unit.objects.get(code="PCS"),
            "hsn_code": "1905",
            "base_price": Decimal("10.00"),
            **extra,
        }
        product: Product = Product.objects.create(**fields)
        ProductTaxRate.objects.create(
            product=product, gst_rate=Decimal("5"), effective_from=today_ist()
        )
        services.ensure_levels_exist([product.pk], services.default_warehouse())
        return product
