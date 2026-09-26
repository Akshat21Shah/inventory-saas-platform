"""What shops see of stock (PLAN §5.3, ADR-041 item 12). Read-only; never the stock itself unless
⚙ ``stock.show_exact_quantity`` is on.

- IN_STOCK: more than the reorder level is available (or any, with no reorder level).
- LOW_STOCK: 0 < available ≤ reorder level, when ⚙ ``stock.show_low_stock_label`` (else IN_STOCK).
- BACKORDER: nothing available and ⚙ ``backorders.enabled`` ("Available on backorder").
- OUT_OF_STOCK: nothing available and backorders off. Hidden from the shop instead when
  ⚙ ``stock.show_out_of_stock_in_shop`` is off.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from django.db.models import DecimalField, F, OuterRef, Q, QuerySet, Subquery, Value
from django.db.models.functions import Coalesce

from apps.catalog.models import Product
from apps.inventory.models import StockLevel
from apps.inventory.services import default_warehouse
from apps.platform.selectors import get_setting

QTY = DecimalField(max_digits=14, decimal_places=3)


class Label:
    IN_STOCK = "IN_STOCK"
    LOW_STOCK = "LOW_STOCK"
    BACKORDER = "BACKORDER"
    OUT_OF_STOCK = "OUT_OF_STOCK"


LABELS = [Label.IN_STOCK, Label.LOW_STOCK, Label.BACKORDER, Label.OUT_OF_STOCK]


@dataclass(frozen=True)
class ShopStockRules:
    show_exact_quantity: bool = False
    show_low_stock_label: bool = True
    backorders_enabled: bool = True
    show_out_of_stock: bool = True

    @classmethod
    def for_tenant(cls, tenant_id: UUID) -> "ShopStockRules":
        return cls(
            show_exact_quantity=bool(get_setting("stock.show_exact_quantity", tenant_id)),
            show_low_stock_label=bool(get_setting("stock.show_low_stock_label", tenant_id)),
            backorders_enabled=bool(get_setting("backorders.enabled", tenant_id)),
            show_out_of_stock=bool(get_setting("stock.show_out_of_stock_in_shop", tenant_id)),
        )

    @property
    def hides_unavailable(self) -> bool:
        return not self.backorders_enabled and not self.show_out_of_stock


@dataclass(frozen=True)
class Availability:
    status: str
    quantity: Decimal | None  # only with stock.show_exact_quantity


def with_available(qs: QuerySet[Product]) -> QuerySet[Product]:
    """Annotate ``stock_available`` (on hand minus reserved in the default warehouse; 0 without a
    stock level)."""
    level = StockLevel.objects.filter(product=OuterRef("pk"), warehouse=default_warehouse())
    available = level.annotate(free=F("quantity_on_hand") - F("quantity_reserved")).values("free")
    return qs.annotate(
        stock_available=Coalesce(
            Subquery(available[:1], output_field=QTY), Value(Decimal("0"), output_field=QTY)
        )
    )


def for_shop(qs: QuerySet[Product], rules: ShopStockRules) -> QuerySet[Product]:
    """``with_available`` plus, when the tenant hides them, no products that can't be ordered."""
    qs = with_available(qs)
    if rules.hides_unavailable:
        qs = qs.filter(Q(stock_available__gt=0))
    return qs


def availability(available: Decimal, reorder_level: Decimal, rules: ShopStockRules) -> Availability:
    if available <= 0:
        status = Label.BACKORDER if rules.backorders_enabled else Label.OUT_OF_STOCK
    elif reorder_level > 0 and available <= reorder_level and rules.show_low_stock_label:
        status = Label.LOW_STOCK
    else:
        status = Label.IN_STOCK
    quantity = max(available, Decimal("0")) if rules.show_exact_quantity else None
    return Availability(status, quantity)
