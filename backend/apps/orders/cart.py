"""Server-side carts (spec 5.8): one per (shop, user), so a staff member ordering for a shop never
touches the shop's own cart (ADR-044). The cart stores products and quantities only; prices, tax,
stock and credit are worked out fresh every time (``quote.build_quote``)."""

from decimal import Decimal
from uuid import UUID

from django.db import transaction

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.inventory.availability import ShopStockRules
from apps.orders.models import Cart, CartLine
from apps.orders.quote import OrderRules, Quote, build_quote
from apps.platform.selectors import get_setting
from apps.retailers.models import Retailer
from apps.shop.selectors import visible_products
from common.errors import InvalidFields, NotFound

MAX_QTY = Decimal("100000")
MAX_LINES = 200
QTY_STEP = Decimal("0.001")


def live_rules(tenant_id: UUID) -> OrderRules:
    return OrderRules.from_settings(lambda key: get_setting(key, tenant_id))


def cart_for(retailer: Retailer, user: User) -> Cart:
    cart: Cart
    cart, _ = Cart.objects.get_or_create(retailer=retailer, user=user)
    return cart


def items(cart: Cart) -> list[tuple[UUID, Decimal]]:
    return [(line.product_id, line.quantity) for line in cart.lines.all()]


def quote(cart: Cart, *, address_id: UUID | None = None) -> Quote:
    retailer = cart.retailer
    return build_quote(
        retailer,
        items(cart),
        rules=live_rules(retailer.tenant_id),
        stock_rules=ShopStockRules.for_tenant(retailer.tenant_id),
        address_id=address_id,
    )


def _valid_qty(product: Product, qty: Decimal) -> Decimal:
    if qty < 0 or qty > MAX_QTY or qty != qty.quantize(QTY_STEP):
        raise InvalidFields({"quantity": ["Enter a quantity between 0 and 100,000."]})
    if not product.unit.allows_decimal and qty % 1:
        raise InvalidFields({"quantity": [f"{product.unit.name} is counted in whole numbers."]})
    return qty


@transaction.atomic
def set_quantity(cart: Cart, product_id: UUID, qty: Decimal) -> None:
    """Set a product's quantity (0 removes it). Only products this shop can see can be added;
    minimums and multiples are reported by the quote, so the shop can still type freely."""
    line = CartLine.objects.select_for_update().filter(cart=cart, product_id=product_id).first()
    if qty == 0:
        if line is not None:
            line.delete()
        return
    product = (
        visible_products(cart.retailer).filter(pk=product_id).select_related("unit").first()
        if line is None
        else Product.objects.select_related("unit").get(pk=product_id)
    )
    if product is None:
        raise NotFound("This product isn't available.")
    qty = _valid_qty(product, qty)
    if line is None:
        if cart.lines.count() >= MAX_LINES:
            raise InvalidFields({"quantity": [f"A cart can hold up to {MAX_LINES} products."]})
        CartLine.objects.create(cart=cart, product=product, quantity=qty)
    else:
        line.quantity = qty
        line.save(update_fields=["quantity", "updated_at"])
    cart.save(update_fields=["updated_at"])


@transaction.atomic
def add_quantities(cart: Cart, wanted: list[tuple[UUID, Decimal]]) -> list[UUID]:
    """Add each product's quantity to what the cart already has (repeat an order). Products the
    shop can no longer see are skipped and returned."""
    visible = set(
        visible_products(cart.retailer)
        .filter(pk__in=[pid for pid, _ in wanted])
        .values_list("pk", flat=True)
    )
    skipped: list[UUID] = []
    for product_id, qty in wanted:
        if product_id not in visible or qty <= 0:
            skipped.append(product_id)
            continue
        line = CartLine.objects.filter(cart=cart, product_id=product_id).first()
        set_quantity(cart, product_id, (line.quantity if line else Decimal("0")) + qty)
    return skipped


@transaction.atomic
def clear(cart: Cart) -> None:
    cart.lines.all().delete()
    cart.save(update_fields=["updated_at"])


@transaction.atomic
def reduce_to_available(cart: Cart) -> None:
    """With backorders off: trim each line to what can be sent now (drop lines with nothing)."""
    current = quote(cart)
    for line in current.lines:
        if line.later_qty > 0 and not line.is_free:  # free lines follow what is bought
            set_quantity(cart, line.product_id, line.ready_qty)
