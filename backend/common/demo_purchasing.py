"""Purchasing and stock planning for the volume distributors (ADR-053, 9a.8), for the speed check.

Added to a distributor that already has its year of trading (``demo_volume``): the
``purchasing`` and ``stock_planning`` modules on, about one supplier per 40 products, every
product linked to a preferred supplier (a third also to a second one) with delivery days, packs
and last costs, the past goods receipts linked to suppliers, a received purchase order for each
past receipt, open orders (some late, some partly received) and drafts, then the product stats
and reorder suggestions worked out by the services. Bulk-inserted like the rest of the volume
data; DEBUG only. Left alone when the distributor already has suppliers.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from apps.accounts.models import User
from apps.billing.tax import round2, stock_value
from apps.catalog.models import Product
from apps.catalog.selectors import tax_rates_on
from apps.inventory.models import StockInward, StockInwardLine, Warehouse
from apps.planning import services as planning
from apps.planning import suggestions
from apps.platform.models import FeatureFlag, Tenant, TenantFeature
from apps.platform.selectors import invalidate_tenant_features
from apps.platform.validators import gstin_check_char
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Supplier, SupplierProduct
from common.dates import IST, today_ist
from common.ids import uuid7
from common.models import Sequence
from common.tenancy import tenant_context

ZERO = Decimal("0")
WORDS = ("Shree", "Om", "Mahalaxmi", "Navkar", "Jai Ambe", "Bharat", "Sai", "Ganesh", "Krishna")
KINDS = ("Traders", "Distributors", "Agencies", "Enterprises", "Marketing", "Wholesale")
PACKS = (None, Decimal("6"), Decimal("10"), Decimal("12"), Decimal("24"))
S = PurchaseOrder.Status


@dataclass(frozen=True)
class Result:
    suppliers: int
    links: int
    orders: int
    order_lines: int
    receipts_linked: int
    suggestions: int


def _gstin(state: str, rng: random.Random) -> str:
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
    pan = "".join(rng.choice(letters) for _ in range(3)) + "F" + rng.choice(letters)
    pan += f"{rng.randrange(1000, 9999)}" + rng.choice(letters)
    first14 = f"{state}{pan}1Z"
    return first14 + gstin_check_char(first14)


def _modules_on(tenant: Tenant) -> None:
    for code in ("purchasing", "stock_planning"):
        TenantFeature.objects.update_or_create(
            flag=FeatureFlag.objects.get(code=code), defaults={"enabled": True}
        )
    invalidate_tenant_features(tenant.pk)


def seed_purchasing(tenant: Tenant, *, seed: int = 9) -> Result | None:
    """Inside the caller's transaction; ``None`` when the distributor already has suppliers."""
    rng = random.Random(f"{tenant.slug}:purchasing:{seed}")  # noqa: S311 - demo data
    with tenant_context(tenant.pk):
        if Supplier.objects.exists():
            return None
        _modules_on(tenant)
        t = tenant.pk
        owner = User.objects.filter(email=f"owner@{tenant.slug}.example.com").first()
        by = owner.pk if owner else None
        products = list(
            Product.objects.filter(deleted_at__isnull=True).select_related("unit").order_by("code")
        )
        categories = sorted({str(p.category_id) for p in products})
        today = today_ist()

        # Suppliers, about one per 40 products, in the distributor's state.
        count = max(8, len(products) // 40)
        suppliers = []
        for n in range(count):
            name = f"{rng.choice(WORDS)} {rng.choice(KINDS)} {n + 1}"
            suppliers.append(
                Supplier(
                    tenant_id=t,
                    code=f"S-{n + 1:04d}",
                    name=name,
                    gstin=_gstin(tenant.state_id, rng),
                    state_id=tenant.state_id,
                    contact_name=f"Contact {n + 1}",
                    phone=f"98{rng.randrange(10_000_000, 99_999_999)}",
                    email=f"orders{n + 1}@supplier.example.com",
                    city=tenant.city,
                    payment_terms_days=rng.choice((0, 15, 30, 45)),
                    lead_time_days=rng.choice((None, 3, 5, 7, 10)),
                    created_by_id=by,
                )
            )
        Supplier.objects.bulk_create(suppliers)
        Sequence.objects.update_or_create(
            name="supplier_code", period="all", defaults={"next_value": count + 1}
        )

        # Every product with a preferred supplier (by its category), a third with a second one.
        links: list[SupplierProduct] = []
        preferred: dict[UUID, Supplier] = {}
        for product in products:
            first = suppliers[categories.index(str(product.category_id)) % count]
            preferred[product.pk] = first
            pack = product.pack_size or rng.choice(PACKS)
            links.append(
                SupplierProduct(
                    tenant_id=t,
                    supplier=first,
                    product=product,
                    is_preferred=True,
                    supplier_code=f"{first.code}-{product.code}"[:40],
                    lead_time_days=rng.choice((None, None, 4, 6)),
                    pack_size=pack,
                    last_unit_cost=product.cost_price,
                    created_by_id=by,
                )
            )
            if rng.random() < 0.33:
                second = suppliers[(suppliers.index(first) + 1) % count]
                links.append(
                    SupplierProduct(
                        tenant_id=t,
                        supplier=second,
                        product=product,
                        is_preferred=False,
                        last_unit_cost=product.cost_price,
                        created_by_id=by,
                    )
                )
        SupplierProduct.objects.bulk_create(links, batch_size=2000)

        # Past receipts: linked to a supplier (allowed once on a posted receipt) and each with a
        # received purchase order sent a few days before.
        warehouse = Warehouse.objects.order_by("created_at").first()
        assert warehouse is not None
        rates = {pk: r.gst_rate for pk, r in tax_rates_on([p.pk for p in products]).items()}
        receipts = list(
            StockInward.objects.filter(status=StockInward.Status.POSTED).order_by("posted_at")
        )
        lines_of: dict[UUID, list[StockInwardLine]] = defaultdict(list)
        for line in StockInwardLine.objects.filter(inward__in=receipts).order_by("line_no"):
            lines_of[line.inward_id].append(line)
        orders: list[PurchaseOrder] = []
        order_lines: list[PurchaseOrderLine] = []
        by_year: dict[int, int] = defaultdict(int)
        by_product = {p.pk: p for p in products}
        linked = 0
        for receipt in receipts:
            received = lines_of.get(receipt.pk, [])
            if not received:
                continue
            supplier = preferred.get(received[0].product_id, suppliers[0])
            linked += StockInward.objects.filter(pk=receipt.pk, supplier__isnull=True).update(
                supplier=supplier
            )
            assert receipt.posted_at is not None
            sent = receipt.posted_at - timedelta(days=rng.randrange(2, 9))
            orders.append(
                _order(
                    t,
                    supplier,
                    warehouse,
                    sent,
                    by_year,
                    S.RECEIVED,
                    by,
                    received_at=receipt.posted_at,
                )
            )
            order_lines += _lines(
                t,
                orders[-1],
                [(by_product[x.product_id], x.quantity, x.unit_cost) for x in received],
                rates,
                by,
                received=True,
            )
        # Open orders now: sent (a third of them late), partly received, and drafts.
        for n in range(max(10, count * 2)):
            supplier = rng.choice(suppliers)
            mine = [p for p in products if preferred[p.pk] is supplier] or products
            picked = rng.sample(mine, min(len(mine), rng.randrange(3, 15)))
            status = (S.SENT, S.SENT, S.PARTLY_RECEIVED, S.DRAFT)[n % 4]
            sent_on = today - timedelta(days=rng.randrange(1, 15))
            sent = timezone_at(sent_on)
            order = _order(t, supplier, warehouse, sent, by_year, status, by)
            orders.append(order)
            order_lines += _lines(
                t,
                order,
                [(p, Decimal(rng.choice((12, 24, 36, 48, 60))), p.cost_price) for p in picked],
                rates,
                by,
                partly=status == S.PARTLY_RECEIVED,
            )
        PurchaseOrder.objects.bulk_create(orders, batch_size=1000)
        PurchaseOrderLine.objects.bulk_create(order_lines, batch_size=2000)
        for year, used in by_year.items():
            Sequence.objects.update_or_create(
                name="purchase_order", period=str(year), defaults={"next_value": used + 1}
            )
        planning.refresh_stats()
        open_count = suggestions.refresh_suggestions()
        return Result(
            suppliers=count,
            links=len(links),
            orders=len(orders),
            order_lines=len(order_lines),
            receipts_linked=linked,
            suggestions=open_count,
        )


def timezone_at(day: Any) -> Any:
    from datetime import datetime, time

    return datetime.combine(day, time(11, 0), tzinfo=IST)


def _order(
    t: UUID,
    supplier: Supplier,
    warehouse: Warehouse,
    sent: Any,
    by_year: dict[int, int],
    status: str,
    by: UUID | None,
    *,
    received_at: Any = None,
) -> PurchaseOrder:
    year = sent.astimezone(IST).year
    by_year[year] += 1
    lead = supplier.lead_time_days or 7
    expected = sent.astimezone(IST).date() + timedelta(days=lead)
    draft = status == S.DRAFT
    return PurchaseOrder(
        id=uuid7(),
        tenant_id=t,
        number=f"PO-{year}-{by_year[year]:05d}",
        supplier=supplier,
        status=status,
        warehouse=warehouse,
        expected_date=expected,
        revision=0 if draft else 1,
        sent_at=None if draft else sent,
        sent_by_id=None if draft else by,
        supplier_snapshot={} if draft else {"code": supplier.code, "name": supplier.name},
        pdf_status="READY" if status == S.RECEIVED else "PENDING",
        created_by_id=by,
        created_at=sent,
        updated_at=received_at or sent,
    )


def _lines(
    t: UUID,
    order: PurchaseOrder,
    items: list[tuple[Product, Decimal, Decimal | None]],
    rates: dict[UUID, Decimal],
    by: UUID | None,
    *,
    received: bool = False,
    partly: bool = False,
) -> list[PurchaseOrderLine]:
    rows = []
    subtotal = tax = ZERO
    for no, (product, quantity, cost) in enumerate(items, 1):
        total = stock_value(quantity, cost) if cost is not None else None
        rate = rates.get(product.pk, ZERO)
        if total is not None:
            subtotal += total
            tax += round2(total * rate / 100)
        got = ZERO
        if received:
            got = quantity
        elif partly and no % 2:
            got = (quantity / 2).quantize(Decimal("1"))
        rows.append(
            PurchaseOrderLine(
                tenant_id=t,
                order=order,
                line_no=no,
                product=product,
                product_code=product.code,
                product_name=product.name,
                unit_code=product.unit.code,
                entered_qty=quantity,
                quantity=quantity,
                unit_cost=cost,
                gst_rate=rate,
                line_total=total,
                qty_received=got,
                created_by_id=by,
            )
        )
    order.subtotal, order.estimated_tax = subtotal, tax
    return rows
