"""Free-goods schemes in orders (ADR-056 items 7-9): free lines in the cart and the order, stock
for them after the bought lines, short stock with backorders off, the bought line losing quantity,
backorder prices, "Repeat last order", the shop's product card, and the module switched off."""

from decimal import Decimal as D
from typing import Any

import pytest
from django.core.cache import cache

from apps.accounts.tests.factories import make_staff_in
from apps.inventory.models import StockLevel
from apps.inventory.tests.helpers import make_product
from apps.orders import backorders
from apps.orders.models import OrderLine
from apps.orders.selectors import repeat_quantities
from apps.orders.tests.helpers import (
    add_stock,
    check_order_invariants,
    make_shop,
    place,
    settings,
    shop_client,
)
from apps.orders.transitions import Modification, modify_order
from apps.platform.models import FeatureFlag, TenantFeature
from apps.platform.selectors import invalidate_tenant_features
from apps.pricing.models import FreeGoodsScheme
from apps.pricing.schemes import Terms, best, headline
from common.errors import InvalidFields
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
SHOP = "/api/v1/shop"


def switch(tenant: Any, on: bool) -> None:
    with tenant_context(tenant.pk):
        TenantFeature.objects.update_or_create(
            flag=FeatureFlag.objects.get(code="free_goods"), defaults={"enabled": on}
        )
    invalidate_tenant_features(tenant.pk)


def scheme(tenant: Any, buy: Any, free: Any, **extra: Any) -> FreeGoodsScheme:
    fields: dict[str, Any] = {
        "name": "Diwali 10+1",
        "buy_qty": D("10"),
        "free_qty": D("1"),
        "audience_type": "ALL",
        **extra,
    }
    with tenant_context(tenant.pk):
        created: FreeGoodsScheme = FreeGoodsScheme.objects.create(
            buy_product=buy, free_product=free, **fields
        )
        return created


@pytest.fixture
def world(tenant_a):
    cache.clear()
    switch(tenant_a, True)
    biscuits = make_product(tenant_a, "P-1", base_price=D("100"))
    tea = make_product(tenant_a, "P-2", base_price=D("50"))
    add_stock(tenant_a, biscuits, "100")
    shop = make_shop(tenant_a, "9876500081", shop_name="Laxmi Stores")
    owner = make_staff_in(tenant_a, "OWNER")
    yield {"t": tenant_a, "p1": biscuits, "p2": tea, "shop": shop, "owner": owner}
    cache.clear()


def lines_of(world: dict[str, Any], order: Any) -> list[OrderLine]:
    with tenant_context(world["t"].pk):
        return list(OrderLine.objects.filter(order=order).order_by("line_no"))


def level(world: dict[str, Any], product: Any) -> StockLevel:
    with tenant_context(world["t"].pk):
        found: StockLevel = StockLevel.objects.get(product=product)
        return found


def test_earned_and_the_next_step():
    t = Terms(
        scheme_id=None,  # type: ignore[arg-type]
        name="10+1",
        buy_product_id=None,  # type: ignore[arg-type]
        buy_qty=D("10"),
        free_product_id=None,  # type: ignore[arg-type]
        free_qty=D("1"),
        repeat=True,
        max_free_qty=D("3"),
    )
    assert [t.earned(D(q)) for q in ("9", "10", "25", "39", "100")] == [0, 1, 2, 3, 3]
    assert t.next_step(D("7")) == (D("3"), D("1"))
    assert t.next_step(D("25")) == (D("5"), D("1"))
    assert t.next_step(D("30")) is None  # the cap is reached
    once = Terms(**{**t.__dict__, "repeat": False, "max_free_qty": None})
    assert (once.earned(D("50")), once.next_step(D("12"))) == (D("1"), None)


def test_the_most_free_units_win_then_the_shop_then_the_newest(world):
    t = world["t"]
    everyone = scheme(t, world["p1"], world["p1"], name="Everyone 10+1")
    shop_only = scheme(
        t,
        world["p1"],
        world["p1"],
        name="Shop 10+1",
        audience_type="RETAILER",
        retailer=world["shop"],
    )
    bigger = scheme(t, world["p1"], world["p1"], name="24+3", buy_qty=D("24"), free_qty=D("3"))
    options = [Terms.of(s) for s in (everyone, shop_only, bigger)]

    def name(found: Terms | None) -> str | None:
        return None if found is None else found.name

    assert name(best(options, D("12"))) == "Shop 10+1"  # same units: the shop's own scheme
    assert name(best(options, D("24"))) == "24+3"  # 3 free against 2
    assert best(options, D("5")) is None
    assert name(headline(options)) == "Shop 10+1"


def test_the_cart_shows_free_lines_and_what_to_add(world):
    scheme(world["t"], world["p1"], world["p1"])
    client = shop_client(world["t"], world["shop"])
    cart = client.put(
        f"{SHOP}/cart/lines/{world['p1'].pk}/", {"quantity": "25"}, format="json"
    ).json()
    paid, free = cart["lines"]
    assert (paid["is_free"], free["is_free"]) == (False, True)
    assert free["quantity"] == "2.000" and free["unit_price"] == "0.00"
    assert free["line_total"] == "0.00" and free["free_of_product_id"] == str(world["p1"].pk)
    assert free["scheme"]["name"] == "Diwali 10+1" and free["scheme"]["same_product"] is True
    assert paid["offer"]["add_qty"] == "5.000" and paid["offer"]["free_qty"] == "1.000"
    assert cart["item_count"] == 1
    assert cart["totals"]["grand_total"] == "2625.00"  # 25 x 100 + 5% GST: the free units add 0
    # The product card says so too.
    card = client.get(f"{SHOP}/products/{world['p1'].pk}/").json()
    assert (card["free_offer"]["buy_qty"], card["free_offer"]["free_qty"]) == ("10.000", "1.000")
    listed = client.get(f"{SHOP}/products/").json()["results"]
    assert [(p["code"], p["free_offer"] is not None) for p in listed] == [
        ("P-1", True),
        ("P-2", False),
    ]


def test_the_order_holds_free_lines_with_the_stock_after_the_bought_lines(world):
    t = world["t"]
    scheme(t, world["p1"], world["p2"], name="Tea free")
    add_stock(t, world["p2"], "1")
    order = place(t, world["shop"], (world["p1"], "20"))
    paid, free = lines_of(world, order)
    assert (free.product_id, free.qty_ordered, free.free_of_line_id) == (
        world["p2"].pk,
        D("2"),
        paid.pk,
    )
    assert (free.qty_reserved, free.qty_backordered) == (D("1"), D("1"))  # backorders on
    assert (free.unit_price, free.line_total, free.price_source) == (D("0"), D("0"), "SCHEME")
    assert free.scheme_name == "Tea free"
    assert free.scheme_rule == {
        "buy_qty": "10",
        "free_qty": "1",
        "repeat": True,
        "max_free_qty": None,
    }
    assert order.grand_total == D("2100.00")
    check_order_invariants(t)


def test_free_units_of_the_same_product_never_take_what_the_bought_line_needs(world):
    t = world["t"]
    other = make_product(t, "P-3", base_price=D("100"))
    add_stock(t, other, "10")
    scheme(t, other, other)
    order = place(t, world["shop"], (other, "10"))
    paid, free = lines_of(world, order)
    assert (paid.qty_reserved, free.qty_reserved, free.qty_backordered) == (D("10"), 0, D("1"))
    assert level(world, other).quantity_reserved == D("10")
    check_order_invariants(t)


def test_with_backorders_off_short_free_goods_are_cut_and_the_shop_is_told(world):
    t = world["t"]
    settings(t, backorders__enabled=False)
    scheme(t, world["p1"], world["p2"])  # no tea in stock
    client = shop_client(t, world["shop"])
    cart = client.put(
        f"{SHOP}/cart/lines/{world['p1'].pk}/", {"quantity": "10"}, format="json"
    ).json()
    free = cart["lines"][1]
    assert [p["code"] for p in free["problems"]] == ["FREE_GOODS_REDUCED"]
    assert cart["can_place"] is True
    order = place(t, world["shop"], (world["p1"], "10"))
    _, free_line = lines_of(world, order)
    assert (free_line.qty_ordered, free_line.qty_cancelled) == (D("1"), D("1"))
    check_order_invariants(t)


def test_reducing_the_cart_to_what_is_there_leaves_free_lines_alone(world):
    t = world["t"]
    settings(t, backorders__enabled=False)
    exact = make_product(t, "P-5", base_price=D("10"))
    add_stock(t, exact, "10")  # all for the bought line; none left for the free unit
    scheme(t, exact, exact)
    client = shop_client(t, world["shop"])
    client.put(f"{SHOP}/cart/lines/{exact.pk}/", {"quantity": "10"}, format="json")
    cart = client.post(f"{SHOP}/cart/reduce-to-available/").json()
    assert [(x["quantity"], x["is_free"], x["ready_qty"]) for x in cart["lines"]] == [
        ("10.000", False, "10.000"),
        ("1.000", True, "0.000"),
    ]


def test_a_smaller_bought_line_keeps_only_the_free_goods_it_earns(world):
    t, owner = world["t"], world["owner"]
    scheme(t, world["p1"], world["p1"])
    order = place(t, world["shop"], (world["p1"], "20"))
    paid, free = lines_of(world, order)
    assert free.qty_reserved == D("2")
    with tenant_context(t.pk):
        modify_order(order.pk, Modification({paid.pk: D("15")}, []), by=owner)
    _, free = lines_of(world, order)
    assert (free.qty_ordered, free.qty_cancelled, free.qty_reserved) == (D("2"), D("1"), D("1"))
    assert level(world, world["p1"]).quantity_reserved == D("16")
    check_order_invariants(t)


def test_a_free_line_is_not_raised_on_its_own(world):
    t, owner = world["t"], world["owner"]
    settings(t, orders__pre_acceptance_edit_mode="FULL_EDIT")
    scheme(t, world["p1"], world["p1"])
    order = place(t, world["shop"], (world["p1"], "10"))
    _, free = lines_of(world, order)
    with tenant_context(t.pk), pytest.raises(InvalidFields):
        modify_order(order.pk, Modification({free.pk: D("5")}, []), by=owner)


def test_cancelling_the_wait_on_a_bought_line_trims_its_free_goods(world):
    t, owner = world["t"], world["owner"]
    short = make_product(t, "P-4", base_price=D("10"))
    add_stock(t, short, "12")
    scheme(t, short, world["p2"])  # no tea in stock: the free units wait too
    order = place(t, world["shop"], (short, "30"))  # 12 now, 18 waiting; 3 free
    paid, free = lines_of(world, order)
    assert (paid.qty_backordered, free.qty_backordered) == (D("18"), D("3"))
    from apps.orders.transitions import accept_order

    with tenant_context(t.pk):
        accept_order(order.pk, by=owner)
        backorders.cancel_backorder(paid.pk, by=owner)
    _, free = lines_of(world, order)
    assert (free.qty_backordered, free.qty_cancelled) == (D("1"), D("2"))  # 12 kept earns 1
    assert level(world, world["p2"]).quantity_backordered == D("1")
    check_order_invariants(t)


def test_free_units_already_in_a_shipment_stay_there(world):
    """[assumed] Only what still waits is cancelled; the warehouse can pack fewer."""
    t, owner = world["t"], world["owner"]
    short = make_product(t, "P-4", base_price=D("10"))
    add_stock(t, short, "12")
    scheme(t, short, world["p1"])  # plenty of biscuits: the free units ship at once
    order = place(t, world["shop"], (short, "30"))
    paid, _ = lines_of(world, order)
    from apps.orders.transitions import accept_order

    with tenant_context(t.pk):
        accept_order(order.pk, by=owner)
        backorders.cancel_backorder(paid.pk, by=owner)
    _, free = lines_of(world, order)
    assert (free.qty_allocated, free.qty_cancelled) == (D("3"), 0)
    check_order_invariants(t)


def test_free_goods_stay_free_when_backorders_take_todays_price(world):
    t = world["t"]
    settings(t, backorders__billing_price="CURRENT")
    scheme(t, world["p1"], world["p2"])
    order = place(t, world["shop"], (world["p1"], "10"))
    _, free = lines_of(world, order)
    with tenant_context(t.pk):
        order.refresh_from_db()
        assert backorders._billing_terms(order, free, D("1")) == (D("0"), False, None)


def test_repeat_last_order_leaves_free_lines_out(world):
    scheme(world["t"], world["p1"], world["p2"])
    order = place(world["t"], world["shop"], (world["p1"], "10"))
    with tenant_context(world["t"].pk):
        order.refresh_from_db()
        assert repeat_quantities(order) == [(world["p1"].pk, D("10"))]


def test_switched_off_nothing_is_free(world):
    t = world["t"]
    scheme(t, world["p1"], world["p1"])
    switch(t, False)
    client = shop_client(t, world["shop"])
    cart = client.put(
        f"{SHOP}/cart/lines/{world['p1'].pk}/", {"quantity": "20"}, format="json"
    ).json()
    assert [line["is_free"] for line in cart["lines"]] == [False]
    assert cart["lines"][0]["offer"] is None
    assert client.get(f"{SHOP}/products/{world['p1'].pk}/").json()["free_offer"] is None
    order = place(t, world["shop"], (world["p1"], "20"))
    assert len(lines_of(world, order)) == 1


def test_another_distributors_scheme_never_applies(world, tenant_b):
    switch(tenant_b, True)
    their = make_product(tenant_b, "P-1", base_price=D("100"))
    scheme(tenant_b, their, their)
    order = place(world["t"], world["shop"], (world["p1"], "20"))
    assert len(lines_of(world, order)) == 1
