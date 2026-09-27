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


def check_invariants(tenant: Any) -> None:
    """Every stock level agrees with its movement log (PLAN §5.5)."""
    from django.db.models import Sum

    from apps.inventory.models import StockLevel, StockMovement

    with tenant_context(tenant.pk):
        for level in StockLevel.objects.all():
            assert level.quantity_on_hand >= 0
            assert 0 <= level.quantity_reserved <= level.quantity_on_hand
            moves = StockMovement.objects.filter(
                product_id=level.product_id, warehouse_id=level.warehouse_id
            )
            totals = moves.aggregate(on_hand=Sum("delta_on_hand"), reserved=Sum("delta_reserved"))
            assert level.quantity_on_hand == (totals["on_hand"] or 0)
            assert level.quantity_reserved == (totals["reserved"] or 0)
            last = moves.order_by("-created_at", "-id").first()
            if last is not None:
                assert (last.on_hand_after, last.reserved_after) == (
                    level.quantity_on_hand,
                    level.quantity_reserved,
                )
