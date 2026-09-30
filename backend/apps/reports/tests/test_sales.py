"""Sales reports (ADR-050 items 3-5) on a small distributor: two bills on two days and a return,
own-brand and traded products, one product costed only after it was billed (estimated) and one
never costed, a nested category, and two shops (one with a salesperson)."""

from datetime import date
from decimal import Decimal as D
from typing import Any

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.billing import credit_notes
from apps.billing.credit_notes import ReturnLine
from apps.billing.models import Invoice
from apps.billing.tests.helpers import ship_invoice
from apps.catalog.models import Brand, Category, Product
from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import add_stock, client_for, make_shop, settings
from apps.retailers.models import Retailer
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
API = "/api/v1"
DAY1, DAY2 = date(2026, 9, 1), date(2026, 9, 2)
PERIOD = "date_from=2026-09-01&date_to=2026-09-03"


@pytest.fixture
def world(tenant_a, tenant_b, monkeypatch):
    owner = make_staff_in(tenant_a, "OWNER")
    sales = make_staff_in(tenant_a, "SALES")
    with tenant_context(tenant_a.pk):
        food = Category.objects.create(name="Food", slug="food")
        biscuits = Category.objects.create(name="Biscuits", slug="biscuits", parent=food, level=2)
        drinks = Category.objects.create(name="Drinks", slug="drinks")
        gold = Brand.objects.create(name="Sharma Gold", own_brand=True)
        parle = Brand.objects.create(name="Parle")
    own = make_product(
        tenant_a, "OWN", base_price=D("100"), cost_price=D("60"), category=biscuits, brand=gold
    )
    traded = make_product(
        tenant_a, "TRD", base_price=D("50"), cost_price=D("30"), category=drinks, brand=parle
    )
    later = make_product(tenant_a, "LATER", base_price=D("20"))  # costed after it was billed
    never = make_product(tenant_a, "NEVER", base_price=D("10"))  # no cost price at all
    for p in (own, traded, later, never):
        add_stock(tenant_a, p, "50")
    shop_a = make_shop(tenant_a, "9876500061", shop_name="Anand Stores")
    shop_b = make_shop(tenant_a, "9876500062", shop_name="Balaji Mart")
    with tenant_context(tenant_a.pk):
        Retailer.objects.filter(pk=shop_a.pk).update(salesperson=sales)

    def on(day: date) -> None:  # bills and credit notes are dated "today"
        monkeypatch.setattr("apps.billing.invoicing.today_ist", lambda: day)
        monkeypatch.setattr("apps.billing.credit_notes.today_ist", lambda: day)

    on(DAY1)
    first = ship_invoice(tenant_a, shop_a, owner, (own, "2"), (traded, "1"))
    on(DAY2)
    second = ship_invoice(tenant_a, shop_b, owner, (traded, "2"), (later, "1"), (never, "1"))
    with tenant_context(tenant_a.pk):
        line = first.lines.get(product=own)
        credit_notes.issue_return(
            first.pk, [ReturnLine(line.pk, D("1"))], reason="DAMAGED", by=owner
        )
        Product.objects.filter(pk=later.pk).update(cost_price=D("12"))
        Retailer.objects.filter(pk=shop_a.pk).update(salesperson=None)  # later: not the sale's
    return {
        "t": tenant_a,
        "owner": client_for(tenant_a, owner),
        "sales": client_for(tenant_a, sales),
        "sales_user": sales,
        "accounts": client_for(tenant_a, make_staff_in(tenant_a, "ACCOUNTS")),
        "other": client_for(tenant_b, make_staff_in(tenant_b, "OWNER")),
        "first": first,
        "second": second,
        "food": food,
        "gold": gold,
    }


def report(client: Any, code: str, query: str = "") -> dict[str, Any]:
    response = client.get(f"{API}/reports/{code}/?{PERIOD}&{query}")
    assert response.status_code == 200, response.json()
    body: dict[str, Any] = response.json()
    return body


def by_name(body: dict[str, Any], key: str = "name") -> dict[str, dict[str, Any]]:
    return {r[key]: r for r in body["rows"]}


def test_the_sales_summary_is_bills_minus_credit_notes_per_day(world):
    body = report(world["owner"], "sales_summary")
    rows = {r["period"]: r for r in body["rows"]}
    assert list(rows) == ["01-09-2026", "02-09-2026", "03-09-2026"]  # every day, even empty
    assert (rows["01-09-2026"]["invoices"], rows["01-09-2026"]["taxable"]) == (1, "250.00")
    assert (rows["02-09-2026"]["invoices"], rows["02-09-2026"]["taxable"]) == (1, "30.00")
    assert rows["03-09-2026"]["total"] == "0.00"
    assert body["totals"]["taxable"] == "280.00"  # 250 + 130 - 100 returned
    total = D(body["totals"]["total"])
    assert D(body["totals"]["billed"]) - D(body["totals"]["credited"]) == total
    month = report(world["owner"], "sales_summary", "group_by=month")
    assert [r["period"] for r in month["rows"]] == ["Sep 2026"]


def test_sales_by_product_with_margins_estimated_and_missing_costs(world):
    body = report(world["owner"], "sales_by_product")
    rows = by_name(body, "code")
    assert (rows["OWN"]["qty"], rows["OWN"]["taxable"]) == ("1.000", "100.00")  # 2 - 1 returned
    assert (rows["OWN"]["cost"], rows["OWN"]["margin"], rows["OWN"]["margin_pct"]) == (
        "60.00",
        "40.00",
        "40.0",
    )
    assert (rows["TRD"]["qty"], rows["TRD"]["cost"], rows["TRD"]["margin"]) == (
        "3.000",
        "90.00",
        "60.00",
    )
    assert (rows["LATER"]["cost"], rows["LATER"]["margin"]) == ("12.00", "8.00")  # estimated
    assert (rows["NEVER"]["cost"], rows["NEVER"]["margin_pct"]) == ("0.00", None)
    assert body["totals"]["taxable"] == "280.00"
    assert body["notes"] == [
        "1 line(s) had no cost recorded when invoiced: today's cost price is used (estimated).",
        "1 line(s) have no cost price and are left out of the margin.",
    ]
    assert body["rows"][0]["code"] == "TRD"  # the biggest first
    # A salesperson sees sales but never costs.
    theirs = report(world["sales"], "sales_by_product")
    assert "cost" not in theirs["rows"][0] and theirs["notes"] == []
    assert "margin" not in theirs["totals"]


def test_filters_by_category_with_its_subcategories_and_by_brand(world):
    food = report(world["owner"], "sales_by_product", f"category={world['food'].pk}")
    assert [r["code"] for r in food["rows"]] == ["OWN"]  # Biscuits is under Food
    gold = report(world["owner"], "sales_by_brand", f"brand={world['gold'].pk}")
    assert [(r["name"], r["own_brand"]) for r in gold["rows"]] == [("Sharma Gold", "Yes")]
    categories = by_name(report(world["owner"], "sales_by_category"))
    assert set(categories) == {"Food > Biscuits", "Drinks", "No category"}


def test_sales_by_shop_and_by_the_salesperson_of_the_order(world):
    shops = by_name(report(world["owner"], "sales_by_shop"))
    assert (shops["Anand Stores"]["invoices"], shops["Anand Stores"]["taxable"]) == (1, "150.00")
    assert shops["Balaji Mart"]["last_invoice"] == "2026-09-02"
    people = report(world["owner"], "sales_by_salesperson")
    rows = {r["name"]: r for r in people["rows"]}
    # The first bill's order was placed while Anand Stores had a salesperson.
    assert rows[world["sales_user"].full_name]["taxable"] == "150.00"
    assert rows["No salesperson"]["taxable"] == "130.00"
    # Sales staff limited to their own shops (the shop is no longer theirs: nothing).
    settings(world["t"], orders__sales_visibility="ASSIGNED_RETAILERS")
    with tenant_context(world["t"].pk):
        Retailer.objects.filter(shop_name="Anand Stores").update(salesperson=world["sales_user"])
    mine = report(world["sales"], "sales_by_shop")
    assert ([r["name"] for r in mine["rows"]], mine["own_shops"]) == (["Anand Stores"], True)


def test_own_brand_against_traded_needs_costs(world):
    body = report(world["accounts"], "margin_own_vs_traded")
    rows = by_name(body)
    assert (rows["Own brand"]["taxable"], rows["Own brand"]["margin"]) == ("100.00", "40.00")
    assert (rows["Traded"]["cost"], rows["Traded"]["margin"]) == ("102.00", "68.00")
    assert body["rows"][0]["name"] == "Own brand"
    brands = report(world["owner"], "margin_own_vs_traded", "group_by=brand")
    assert brands["rows"][0]["name"] == "Sharma Gold"
    assert world["sales"].get(f"{API}/reports/margin_own_vs_traded/?{PERIOD}").status_code == 403


def test_a_bill_whose_irn_was_cancelled_is_not_a_sale(world):
    with tenant_context(world["t"].pk):
        Invoice.objects.filter(pk=world["second"].pk).update(status="CANCELLED")
    assert report(world["owner"], "sales_summary")["totals"]["taxable"] == "150.00"  # 250 - 100


def test_another_business_sees_none_of_it(world):
    assert report(world["other"], "sales_by_product")["rows"] == []
    assert report(world["other"], "sales_summary")["totals"]["total"] == "0.00"
