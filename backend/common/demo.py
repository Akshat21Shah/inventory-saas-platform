"""Phase 2 demo data for ``manage.py seed``: per distributor, a 3-level category tree, brands,
200 products with photos, 20 shops, two price lists, special prices and discount rules.

Everything goes through the normal services (validation, audit). Deterministic per distributor
and idempotent: existing codes, shops and names are left alone. HSN codes and GST rates here are
demo values chosen from the active platform rates, not tax guidance.
"""

import io
import random
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageDraw

from apps.accounts.models import Membership, User
from apps.catalog import services as catalog
from apps.catalog.models import Brand, Category, Product, Unit
from apps.inventory import adjustments, receipts
from apps.inventory.adjustments import AdjustmentInput, AdjustmentLineInput
from apps.inventory.models import AdjustmentReason, StockAdjustment, StockInward
from apps.inventory.receipts import LineInput, ReceiptInput
from apps.platform.models import TaxRate, Tenant
from apps.platform.validators import gstin_check_char
from apps.pricing import services as pricing
from apps.pricing.models import DiscountRule, PriceList
from apps.retailers.models import Retailer
from apps.retailers.services import AddressInput, block_retailer, create_retailer
from common.dates import today_ist

PRODUCTS_PER_TENANT = 200
SHOPS_PER_TENANT = 20
PAISA = Decimal("0.01")

# (top level, [(level 2, [level 3, ...]), ...], demo HSN, preferred GST rate)
TREE: list[tuple[str, list[tuple[str, list[str]]], str, str]] = [
    (
        "Food",
        [("Biscuits", ["Cream biscuits", "Glucose biscuits"]), ("Snacks", ["Namkeen"])],
        "1905",
        "5",
    ),
    ("Beverages", [("Tea", []), ("Coffee", []), ("Soft drinks", [])], "2202", "18"),
    ("Staples", [("Atta and flour", []), ("Rice", []), ("Oil", [])], "1101", "5"),
    ("Personal care", [("Soap", []), ("Shampoo", []), ("Toothpaste", [])], "3401", "18"),
    ("Home care", [("Detergent", []), ("Cleaners", [])], "3402", "18"),
]
BRANDS = [
    "Parle",
    "Britannia",
    "Haldiram",
    "Tata",
    "Nescafe",
    "Aashirvaad",
    "Fortune",
    "Dove",
    "Colgate",
    "Surf Excel",
    "Vim",
    "Lizol",
]
KINDS = {
    "Cream biscuits": ["Bourbon", "Hide & Seek", "Treat"],
    "Glucose biscuits": ["Glucose", "Marie Gold", "Tiger"],
    "Namkeen": ["Aloo Bhujia", "Moong Dal", "Khatta Meetha"],
    "Tea": ["Premium Tea", "Masala Chai", "Green Tea"],
    "Coffee": ["Classic Coffee", "Filter Coffee"],
    "Soft drinks": ["Lemon Drink", "Mango Drink"],
    "Atta and flour": ["Whole Wheat Atta", "Besan"],
    "Rice": ["Basmati Rice", "Sona Masoori"],
    "Oil": ["Sunflower Oil", "Mustard Oil"],
    "Soap": ["Beauty Bar", "Neem Soap"],
    "Shampoo": ["Anti-dandruff Shampoo", "Herbal Shampoo"],
    "Toothpaste": ["Toothpaste", "Herbal Toothpaste"],
    "Detergent": ["Detergent Powder", "Liquid Detergent"],
    "Cleaners": ["Dishwash Bar", "Floor Cleaner"],
}
SIZES = ["50g", "100g", "200g", "250g", "500g", "1kg", "5kg", "200ml", "500ml", "1L"]
PHONE_BASE = {"sharma": 9876501000, "patel": 9876502000}
SHOP_NAMES = [
    "Laxmi Stores",
    "Sai Kirana",
    "Balaji Traders",
    "Shiv Provision",
    "Maruti General Store",
    "Annapurna Mart",
    "Krishna Kirana",
    "Jai Ambe Stores",
    "Mahalaxmi Traders",
    "Gurukrupa Stores",
    "Siddhivinayak Mart",
    "Om Sai Provision",
    "Navkar Stores",
    "Pooja General Store",
    "Samarth Kirana",
    "Vighnaharta Traders",
    "Datta Provision",
    "Sagar Stores",
    "Shubham Mart",
]


@dataclass
class Summary:
    products: int = 0
    images: int = 0
    shops: int = 0
    rules: int = 0
    stock_documents: int = 0


def _money(value: Decimal) -> Decimal:
    return value.quantize(PAISA, rounding=ROUND_HALF_UP)


def _photo(text: str, color: tuple[int, int, int]) -> SimpleUploadedFile:
    """A simple product "photo": a coloured tile with the product's initials."""
    image = Image.new("RGB", (640, 640), color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 600, 600), outline=(255, 255, 255), width=12)
    draw.text((320, 320), text, fill=(255, 255, 255), anchor="mm", font_size=180)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return SimpleUploadedFile("photo.png", buffer.getvalue(), content_type="image/png")


def _rate(preferred: str, active: set[Decimal]) -> Decimal:
    wanted = Decimal(preferred)
    return wanted if wanted in active else max(active)


def _categories(by: User) -> list[tuple[Category, str, str]]:
    """Leaf categories with their demo HSN code and preferred rate."""
    existing: dict[tuple[Any, str], Category] = {
        (c.parent_id, c.name): c for c in Category.objects.filter(deleted_at__isnull=True)
    }

    def get(name: str, parent: Category | None, order: int) -> Category:
        found = existing.get((parent.pk if parent else None, name))
        if found is not None:
            return found
        return catalog.create_category(
            name=name, parent_id=parent.pk if parent else None, sort_order=order, by=by
        )

    leaves: list[tuple[Category, str, str]] = []
    for order, (top, children, hsn, rate) in enumerate(TREE):
        root = get(top, None, order)
        for child_order, (child, grandchildren) in enumerate(children):
            middle = get(child, root, child_order)
            if not grandchildren:
                leaves.append((middle, hsn, rate))
            for leaf_order, leaf in enumerate(grandchildren):
                leaves.append((get(leaf, middle, leaf_order), hsn, rate))
    return leaves


def _brands(tenant: Tenant, by: User) -> tuple[list[Brand], Brand]:
    """The traded brands, and the distributor's own brand (ADR-039)."""
    have = {b.name: b for b in Brand.objects.filter(deleted_at__isnull=True)}
    traded = [have.get(name) or catalog.save_brand(None, name=name, by=by) for name in BRANDS]
    own_name = f"{tenant.name.split()[0]} Select"
    own = have.get(own_name) or catalog.save_brand(None, name=own_name, own_brand=True, by=by)
    return traded, own


def _products(
    tenant: Tenant, by: User, rng: random.Random, photos: bool, summary: Summary
) -> list[Product]:
    prefix = tenant.slug[:2].upper()
    leaves = _categories(by)
    brands, own_brand = _brands(tenant, by)
    units = {u.code: u for u in Unit.objects.all()}
    active = set(TaxRate.objects.filter(is_active=True, rate__gt=0).values_list("rate", flat=True))
    existing = set(Product.objects.values_list("code", flat=True))
    for n in range(1, PRODUCTS_PER_TENANT + 1):
        code = f"{prefix}-{n:04d}"
        rng_price = Decimal(rng.randrange(800, 60000)) / 100  # always drawn: stable sequence
        category, hsn, preferred = leaves[n % len(leaves)]
        brand = own_brand if n % 10 == 0 else brands[(n * 7) % len(brands)]
        kind = rng.choice(KINDS[category.name])
        size = rng.choice(SIZES)
        box = rng.random() < 0.25
        if code in existing:
            continue
        rate = _rate(preferred, active)
        base = _money(rng_price)
        mrp = _money(base * (100 + rate) / 100 * Decimal("1.15"))
        product, _warnings = catalog.create_product(
            {
                "code": code,
                "name": f"{brand.name} {kind} {size}",
                "description": f"{brand.name} {kind}, {size} pack.",
                "category_id": category.pk,
                "brand_id": brand.pk,
                "unit_id": units["PCS"].pk,
                "pack_unit_id": units["BOX"].pk if box else None,
                "pack_size": Decimal("12") if box else None,
                "hsn_code": hsn,
                "mrp": mrp,
                "base_price": base,
                "cost_price": _money(base * Decimal("0.82" if brand.own_brand else "0.9")),
                "min_order_qty": Decimal("6") if box else Decimal("1"),
                "order_multiple": Decimal("6") if box else Decimal("1"),
                "reorder_level": Decimal("24"),
                "tags": [category.name.lower()],
                # A few internal and discontinued items, to show the shop's visibility rules.
                "show_in_shop": n % 50 != 0,
                "is_active": n % 67 != 0,
            },
            gst_rate=rate,
            by=by,
        )
        summary.products += 1
        if photos:
            color = (rng.randrange(40, 200), rng.randrange(40, 200), rng.randrange(40, 200))
            initials = "".join(word[0] for word in f"{brand.name} {kind}".split()[:2]).upper()
            image = catalog.upload_image(product.pk, _photo(initials, color), by=by)
            catalog.process_image(str(image.pk))  # now, so the demo doesn't wait for the worker
            summary.images += 1
    return list(Product.objects.filter(code__startswith=f"{prefix}-").order_by("code"))


def _gstin(state: str, rng: random.Random) -> str:
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
    pan = "".join(rng.choice(letters) for _ in range(3)) + "P" + rng.choice(letters)
    pan += f"{rng.randrange(1000, 9999)}" + rng.choice(letters)
    first14 = f"{state}{pan}1Z"
    return first14 + gstin_check_char(first14)


def _shops(
    tenant: Tenant, by: User, rng: random.Random, lists: list[PriceList], summary: Summary
) -> list[Retailer]:
    sales = Membership.objects.filter(role__code="SALES").select_related("user").first()
    base = PHONE_BASE[tenant.slug]
    shops = list(Retailer.objects.filter(deleted_at__isnull=True).order_by("code"))
    for index, name in enumerate(SHOP_NAMES):
        if len(shops) >= SHOPS_PER_TENANT:
            break
        phone = str(base + index)
        if Retailer.objects.filter(mobile=f"+91{phone}").exists():
            continue
        registered = index % 3 != 2
        retailer = create_retailer(
            shop_name=name,
            phone=phone,
            contact_name=f"Owner of {name}",
            created_by=by,
            state_id=tenant.state_id,
            gstin=_gstin(tenant.state_id, rng) if registered else None,
            billing=AddressInput(
                line1=f"Shop {index + 1}, Market Road",
                city=tenant.city,
                pincode=tenant.pincode,
                state_id=tenant.state_id,
            ),
            extra={
                "price_list_id": lists[index % 3].pk if index % 3 < len(lists) else None,
                "salesperson_id": sales.user_id if sales and index % 2 == 0 else None,
                "credit_limit": Decimal(25000 + 5000 * (index % 5)),
                "payment_terms_days": 15,
            },
            send_welcome=False,  # demo shops: no messages
        )
        shops.append(retailer)
        summary.shops += 1
    if summary.shops and not Retailer.objects.filter(status=Retailer.Status.BLOCKED).exists():
        block_retailer(shops[-1].pk, reason="Overdue payments (demo)", by=by)  # one shop on hold
    return shops


def _pricing(by: User, products: list[Product], summary: Summary) -> list[PriceList]:
    lists: list[PriceList] = []
    for name, off in (("Gold", Decimal("0.95")), ("Wholesale", Decimal("0.92"))):
        price_list = PriceList.objects.filter(name=name, deleted_at__isnull=True).first()
        if price_list is None:
            price_list = pricing.save_price_list(None, name=name, by=by)
            chosen = products[:: 3 if name == "Gold" else 4]
            pricing.upsert_items(
                price_list.pk,
                [pricing.ItemInput(p.pk, _money(p.base_price * off)) for p in chosen],
                by=by,
            )
        lists.append(price_list)
    return lists


def _rules(
    by: User,
    lists: list[PriceList],
    shops: list[Retailer],
    products: list[Product],
    summary: Summary,
) -> None:
    if DiscountRule.objects.exists():
        return
    biscuits = Category.objects.get(name="Biscuits", deleted_at__isnull=True)
    staples = Category.objects.get(name="Staples", deleted_at__isnull=True)
    parle = Brand.objects.get(name="Parle", deleted_at__isnull=True)
    today = today_ist()
    rules: list[tuple[dict[str, Any], list[pricing.SlabInput] | None]] = [
        (
            {
                "name": "Biscuits: buy more, pay less",
                "discount_type": "PERCENT",
                "value": Decimal("0"),
                "scope_type": "CATEGORY",
                "category_id": biscuits.pk,
                "audience_type": "ALL",
            },
            [
                pricing.SlabInput(Decimal("12"), Decimal("2")),
                pricing.SlabInput(Decimal("24"), Decimal("5")),
            ],
        ),
        (
            {
                "name": "Parle week",
                "discount_type": "PERCENT",
                "value": Decimal("3"),
                "scope_type": "BRAND",
                "brand_id": parle.pk,
                "audience_type": "ALL",
                "valid_from": today - timedelta(days=2),
                "valid_to": today + timedelta(days=12),
            },
            None,
        ),
        (
            {
                "name": "Gold members: staples",
                "discount_type": "FLAT_PER_UNIT",
                "value": Decimal("2"),
                "scope_type": "CATEGORY",
                "category_id": staples.pk,
                "audience_type": "PRICE_LIST",
                "price_list_id": lists[0].pk,
            },
            None,
        ),
        (
            {
                "name": "Diwali offer",
                "discount_type": "PERCENT",
                "value": Decimal("4"),
                "scope_type": "ALL",
                "audience_type": "ALL",
                "valid_from": today + timedelta(days=20),
                "valid_to": today + timedelta(days=35),
            },
            None,
        ),
        (
            {
                "name": "Old monsoon offer (switched off)",
                "discount_type": "PERCENT",
                "value": Decimal("6"),
                "scope_type": "ALL",
                "audience_type": "ALL",
                "is_active": False,
            },
            None,
        ),
    ]
    for data, slabs in rules:
        pricing.save_discount_rule(None, data, slabs, by=by)
        summary.rules += 1
    for shop, product in zip(shops[:5], products[1::40], strict=False):
        pricing.save_retailer_price(
            None,
            retailer_id=shop.pk,
            product_id=product.pk,
            price=_money(product.base_price * Decimal("0.9")),
            note="Agreed deal (demo)",
            by=by,
        )


def _stock(tenant: Tenant, by: User, products: list[Product], summary: Summary) -> None:
    """Opening stock, a shelf count that empties a few products (out of stock) and leaves some low,
    a posted goods receipt with costs, one posted by the warehouse without costs (awaiting cost),
    a draft and a damage adjustment. Only for a tenant with no stock documents yet, so re-running
    the seed never adds stock twice."""
    if StockAdjustment.objects.exists() or StockInward.objects.exists():
        return
    rng = random.Random(f"stock-{tenant.slug}")  # noqa: S311 - demo data, not security
    warehouse = User.objects.get(email=f"warehouse@{tenant.slug}.example.com")
    active = [p for p in products if p.is_active]

    def adjust(reason: str, note: str, lines: list[AdjustmentLineInput], who: User) -> None:
        for start in range(0, len(lines), adjustments.MAX_LINES):
            adjustments.create_adjustment(
                AdjustmentInput(reason, note, lines[start : start + adjustments.MAX_LINES]), by=who
            )
            summary.stock_documents += 1

    def receive(header: dict[str, Any], lines: list[LineInput], who: User, post: bool) -> None:
        if not lines:
            return
        data = ReceiptInput(lines=lines, **header)
        (receipts.create_and_post if post else receipts.create_draft)(data, by=who)
        summary.stock_documents += 1

    adjust(
        AdjustmentReason.OPENING_STOCK,
        "Demo opening stock",
        [AdjustmentLineInput(p.pk, "ADD", Decimal(rng.randrange(40, 400))) for p in products],
        by,
    )
    counted = [
        AdjustmentLineInput(p.pk, "COUNTED", Decimal(0 if n % 2 else rng.randrange(1, 24)))
        for n, p in enumerate(products[6::7])
    ]
    adjust(AdjustmentReason.COUNT_CORRECTION, "Monthly shelf count", counted, warehouse)
    supplier = {"supplier_name": "Demo Wholesale Pvt Ltd"}
    receive(
        {**supplier, "bill_number": "DW/2026/0412", "bill_date": today_ist()},
        [
            LineInput(
                p.pk,
                Decimal("2") if p.pack_unit_id else Decimal("48"),
                "PACK" if p.pack_unit_id else "BASE",
                (p.cost_price or Decimal("10")) * (p.pack_size or 1),
            )
            for p in active[1:40:6]
        ],
        by,
        post=True,
    )
    receive(
        {**supplier, "bill_number": "DW/2026/0419"},
        [LineInput(p.pk, Decimal("24")) for p in active[3:12:4]],
        warehouse,
        post=True,
    )
    receive(
        {"supplier_name": "Sai Agencies"},
        [LineInput(p.pk, Decimal("12")) for p in active[5:7]],
        warehouse,
        post=False,
    )
    if active:
        adjust(
            AdjustmentReason.DAMAGE,
            "Cartons damaged in the rain",
            [AdjustmentLineInput(active[0].pk, "REMOVE", Decimal("2"))],
            warehouse,
        )


def seed_catalog(tenant: Tenant, by: User, *, photos: bool = True) -> Summary:
    """Run inside ``tenant_context(tenant.id)``."""
    rng = random.Random(f"demo-{tenant.slug}")  # noqa: S311 - demo data, not security
    summary = Summary()
    products = _products(tenant, by, rng, photos, summary)
    lists = _pricing(by, products, summary)
    shops = _shops(tenant, by, rng, lists, summary)
    _rules(by, lists, shops, products, summary)
    _stock(tenant, by, products, summary)
    return summary
