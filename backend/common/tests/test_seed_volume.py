"""The volume seed (ADR-050 item 13) on a small scale: its simulated year agrees with itself the
way the services keep it, the dashboard and every report open on it, and the sales reports agree
with each other and with the invoices."""

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
    assert len(codes) == 18
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
