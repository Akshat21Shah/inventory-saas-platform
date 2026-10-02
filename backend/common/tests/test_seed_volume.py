"""The volume seed (ADR-050 item 13) on a small scale: its simulated year agrees with itself the
way the services keep it, the dashboard and every report open on it, and the sales reports agree
with each other and with the invoices."""

import json
from decimal import Decimal as D

import pytest
from django.core.management import CommandError, call_command
from django.db.models import Sum

from apps.accounts.models import User
from apps.billing.models import CreditNote, Invoice
from apps.inventory.models import StockLevel
from apps.orders.models import Order, OrderStatus
from apps.orders.tests.helpers import client_for
from apps.payments.models import Payment
from apps.platform.models import Tenant
from apps.reports.models import ReportRun
from common.dates import today_ist
from common.demo_volume import VolumeTenant, reconcile, seed_tenant
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db

SMALL = VolumeTenant(
    "vol-t", "Volume Test T", "Volume Test T LLP", "27", "AAKFV9009T", "Pune", "411001",
    orders=300, shops=25, products=60, salespeople=2, other_state="24", phone_base=9_300_900_000,
)  # fmt: skip


@pytest.fixture
def year():
    result = seed_tenant(SMALL, days=120)
    assert result is not None
    return Tenant.objects.get(slug="vol-t"), result


def test_a_simulated_year_agrees_with_itself(year):
    tenant, result = year
    assert result.orders == 300
    with tenant_context(tenant.pk):
        assert reconcile() == []
        statuses = set(Order.objects.values_list("status", flat=True))
        assert {OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.REJECTED} <= statuses
        assert Invoice.objects.count() == result.invoices > 250
        assert Invoice.objects.filter(payment_status="PAID").exists()
        assert Invoice.objects.filter(payment_status="UNPAID").exists()
        assert Payment.objects.count() == result.payments > 0
        assert Payment.objects.filter(handover_status="HANDED_OVER").exists()
        assert StockLevel.objects.filter(quantity_on_hand__gt=0).exists()
        # Invoices dated through the period, not all today.
        first = Invoice.objects.order_by("invoice_date").values_list("invoice_date", flat=True)[0]
        assert first < today_ist()


def test_the_dashboard_and_every_report_open_on_it(year):
    tenant, _result = year
    owner = client_for(tenant, User.objects.get(email="owner@vol-t.example.com"))
    assert owner.get("/api/v1/dashboard/").status_code == 200
    codes = [r["code"] for r in owner.get("/api/v1/reports/").json()]
    assert len(codes) == 20  # + shop activity (ADR-056)
    pages = {}
    for code in codes:
        response = owner.get(f"/api/v1/reports/{code}/")
        assert response.status_code == 200, (code, response.json())
        pages[code] = response.json()
    month = today_ist().replace(day=1)
    with tenant_context(tenant.pk):
        billed = Invoice.objects.filter(invoice_date__gte=month).aggregate(t=Sum("taxable_total"))
        credited = CreditNote.objects.filter(note_date__gte=month).aggregate(t=Sum("taxable_total"))
    net = (billed["t"] or D(0)) - (credited["t"] or D(0))
    for code in ("sales_by_product", "sales_by_shop", "sales_by_category"):
        assert D(pages[code]["totals"]["taxable"]) == net, code


def test_a_second_run_adds_nothing(year):
    assert seed_tenant(SMALL, days=120) is None


def test_the_command_refuses_without_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed_volume")


def test_the_speed_check_times_every_page(year, capsys):
    call_command("perf_reports", "--tenant", "vol-t", "--runs", "2", "--target-ms", "60000")
    out = capsys.readouterr().out
    assert "dashboard" in out and "sales_by_product" in out and "gst_summary" in out
    assert "under 60000 ms" in out


def test_the_export_check_makes_each_export_as_the_worker_does(year, capsys):
    for name in ("sales_by_invoice", "gst_summary", "stock_movements"):
        call_command("perf_exports", "--one", name, "--tenant", "vol-t")
        measured = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert measured["export"] == name
        assert measured["rows"] > 0 and measured["file_mb"] > 0 and measured["peak_mb"] > 0
    with tenant_context(year[0].pk):
        assert not ReportRun.objects.exists()  # a measurement leaves nothing behind


def test_purchasing_and_planning_on_the_volume_data(year, capsys):
    """ADR-053 (9a.8): suppliers, product links, received and open purchase orders, past
    receipts linked, stats and reorder suggestions; then the 9a speed check runs on it."""
    from apps.inventory.models import StockInward
    from apps.planning.models import ProductStats
    from apps.purchasing.models import PurchaseOrder, Supplier, SupplierProduct
    from common.demo_purchasing import seed_purchasing

    tenant, _result = year
    added = seed_purchasing(tenant)
    assert added is not None and added.suppliers == 8
    with tenant_context(tenant.pk):
        products = SupplierProduct.objects.filter(is_preferred=True).count()
        assert products == ProductStats.objects.count() == 60  # every product
        assert Supplier.objects.count() == 8
        statuses = set(PurchaseOrder.objects.values_list("status", flat=True))
        assert {"RECEIVED", "SENT", "PARTLY_RECEIVED", "DRAFT"} <= statuses
        posted = StockInward.objects.filter(status="POSTED")
        assert posted.filter(supplier__isnull=True).count() == 0 < posted.count()
    assert seed_purchasing(tenant) is None  # a second run adds nothing
    owner = client_for(tenant, User.objects.get(email="owner@vol-t.example.com"))
    action = owner.get("/api/v1/dashboard/").json()["action"]
    assert action["to_reorder"] == added.suggestions and action["late_purchase_orders"] is not None
    call_command(
        "perf_search", "--tenant", "vol-t", "--runs", "2", "--target-ms", "60000",
        "--search-target-ms", "60000",
    )  # fmt: skip
    out = capsys.readouterr().out
    assert "search (owner): order unpadded" in out and "jump order 1" in out
    assert "reorder suggestions" in out and "every p95 is under its target" in out


def test_free_goods_and_shop_activity_on_the_volume_data(year):
    """ADR-056 (9b.6): a scheme per 25 products and every shop's activity; a second run adds
    nothing."""
    from apps.insights.models import ShopActivity
    from apps.pricing.models import FreeGoodsScheme
    from common.demo_growth import seed_volume_growth

    tenant, _result = year
    added = seed_volume_growth(tenant)
    assert added is not None and added.schemes == 3  # 60 products
    with tenant_context(tenant.pk):
        assert FreeGoodsScheme.objects.count() == 3
        assert ShopActivity.objects.count() == added.shops > 0
    assert seed_volume_growth(tenant) is None
