import pyotp
import pytest
from django.core.management import CommandError, call_command

from apps.accounts import mfa
from apps.accounts.models import Membership, User
from apps.catalog.models import Category, Product, ProductImage
from apps.platform.models import Tenant
from apps.pricing.models import DiscountRule, PriceList, RetailerPrice
from apps.retailers.models import Retailer
from apps.shop.selectors import ShopFilters, priced, shop_products
from common import demo
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


def test_seed_is_idempotent(settings):
    settings.DEBUG = True
    call_command("seed", "--no-photos")
    call_command("seed", "--no-photos")
    assert User.objects.filter(email="admin@platform.local", is_superuser=True).count() == 1
    assert set(Tenant.objects.values_list("slug", flat=True)) == {"sharma", "patel"}
    sharma = Tenant.objects.get(slug="sharma")
    with tenant_context(sharma.id):
        roles = set(Membership.objects.values_list("role__code", flat=True))
        assert roles == {"OWNER", "MANAGER", "SALES", "WAREHOUSE", "ACCOUNTS"}
        assert Retailer.objects.count() == 20
    owner = User.objects.get(email="owner@sharma.example.com")
    assert owner.check_password("staff-dev-password")
    # The shared shop phone has a login under both distributors (sign-in chooser).
    assert User.objects.filter(phone="+919876500000", user_type=User.UserType.RETAILER).count() == 2
    admin = User.objects.get(email="admin@platform.local")
    assert admin.totp_enabled
    assert mfa.matching_step(admin.totp_secret, pyotp.TOTP(admin.totp_secret).now()) is not None
    # Demo billing (Phase 5): run once, and the ledger reconciles.
    from apps.billing.models import CreditNote, Invoice
    from apps.ledger.tests.helpers import check_ledger
    from apps.payments.models import Payment, Refund

    with tenant_context(sharma.id):
        assert Invoice.objects.exists()
        assert Payment.objects.count() == 4
        assert Payment.objects.filter(handover_status="WITH_SALESMAN").count() == 1
        assert CreditNote.objects.count() == 1
        assert Refund.objects.count() == 1
    check_ledger(sharma)


def test_seed_keeps_an_existing_admin_2fa_key(settings):
    settings.DEBUG = True
    call_command("seed", "--no-photos")
    admin = User.objects.get(email="admin@platform.local")
    admin.totp_secret = pyotp.random_base32()
    admin.save(update_fields=["totp_secret"])
    call_command("seed", "--no-photos")
    admin.refresh_from_db()
    assert admin.totp_secret != "DEVSEEDADMINTOTPKEYDEVSEEDADMIN2"


def test_seed_refuses_without_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed", "--no-photos")


def test_seed_can_put_the_admin_back_on_the_dev_2fa_key(settings):
    settings.DEBUG = True
    call_command("seed", "--no-photos")
    admin = User.objects.get(email="admin@platform.local")
    admin.totp_secret = pyotp.random_base32()
    admin.save(update_fields=["totp_secret"])
    call_command("seed", "--no-photos", "--reset-admin-2fa")
    admin.refresh_from_db()
    assert admin.totp_secret == "DEVSEEDADMINTOTPKEYDEVSEEDADMIN2"


def test_seed_builds_a_catalog_each_shop_can_browse_at_its_own_prices(settings):
    settings.DEBUG = True
    call_command("seed", "--no-photos")
    sharma = Tenant.objects.get(slug="sharma")
    with tenant_context(sharma.id):
        assert Product.objects.count() == 200
        assert Product.objects.filter(brand__own_brand=True).count() == 20
        assert not Product.objects.filter(cost_price__isnull=True).exists()
        assert Category.objects.filter(level=3).exists()
        assert set(PriceList.objects.values_list("name", flat=True)) == {"Gold", "Wholesale"}
        assert DiscountRule.objects.count() == 5 and RetailerPrice.objects.count() == 5
        assert Retailer.objects.filter(status="BLOCKED").count() == 1
        gold_shop = Retailer.objects.filter(price_list__name="Gold").first()
        assert gold_shop is not None
        visible = list(shop_products(gold_shop, ShopFilters()))
        assert 150 < len(visible) < 200  # hidden and inactive items are left out
        sources = {r.price_source for _, r in priced(gold_shop, visible)}
        assert "PRICE_LIST" in sources and "BASE" in sources
    patel = Tenant.objects.get(slug="patel")
    with tenant_context(patel.id):
        assert not Product.objects.filter(code__startswith="SH-").exists()  # no mixing


def test_seed_photos_are_processed(settings, monkeypatch):
    settings.DEBUG = True
    monkeypatch.setattr(demo, "PRODUCTS_PER_TENANT", 3)
    call_command("seed")
    sharma = Tenant.objects.get(slug="sharma")
    with tenant_context(sharma.id):
        statuses = list(ProductImage.objects.values_list("status", flat=True))
    assert statuses == ["READY"] * 3


def test_e2e_workbook_is_an_importable_excel_file(settings, capsys):
    import base64
    import io

    from openpyxl import load_workbook

    settings.DEBUG = True
    call_command("e2e_workbook", "products", "--count", "3", "--prefix", "T1")
    book = load_workbook(io.BytesIO(base64.b64decode(capsys.readouterr().out)))
    rows = list(book.worksheets[0].iter_rows(values_only=True))
    assert rows[0][0] == "Product code" and rows[1][0] == "T1-0001" and len(rows) == 4
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("e2e_workbook", "retailers")


def test_e2e_ids_lists_seeded_records(settings, capsys):
    import json

    settings.DEBUG = True
    call_command("seed", "--no-photos")
    capsys.readouterr()
    call_command("e2e_ids")
    ids = json.loads(capsys.readouterr().out)
    assert set(ids) == {
        "tenant",
        "retailer",
        "product",
        "price_list",
        "rule",
        "import_job",
        "receipt",
        "draft_receipt",
        "adjustment",
        "shop_order",
        "order",
        "fulfilment",
        "backorder_product",
        "invoice",
        "credit_note",
        "payment",
        "refund",
        "shop_invoice",
    }
    assert ids["receipt"] and ids["draft_receipt"] and ids["adjustment"]  # from the demo stock
    assert ids["shop_order"] and ids["order"] and ids["fulfilment"] and ids["backorder_product"]
    assert ids["invoice"] and ids["credit_note"] and ids["payment"] and ids["refund"]  # billing
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("e2e_ids")


def test_seed_adds_demo_stock_once(settings):
    from apps.inventory.models import StockAdjustment, StockAlert, StockInward, StockLevel
    from apps.inventory.tests.helpers import check_invariants

    settings.DEBUG = True
    call_command("seed", "--no-photos")
    call_command("seed", "--no-photos")  # a second run adds nothing
    sharma = Tenant.objects.get(slug="sharma")
    with tenant_context(sharma.id):
        assert StockAdjustment.objects.count() == 3  # opening stock, shelf count, damage
        # Two demo receipts, and the demo orders' receipt that serves a waiting backorder.
        assert StockInward.objects.filter(status="POSTED").count() == 3
        assert StockInward.objects.filter(status="DRAFT").count() == 1
        assert StockInward.objects.filter(cost_pending_lines__gt=0).count() == 2
        assert StockLevel.objects.filter(quantity_on_hand=0).exists()
        alert_types = set(
            StockAlert.objects.filter(status="OPEN").values_list("alert_type", flat=True)
        )
        assert alert_types == {"LOW_STOCK", "OUT_OF_STOCK", "BACKORDER_DEMAND"}
    check_invariants(sharma)


def test_seed_fills_every_order_tab_once(settings):
    from apps.orders.models import BackorderAllocation, Order
    from apps.orders.selectors import TABS
    from apps.orders.tests.helpers import check_order_invariants

    settings.DEBUG = True
    call_command("seed", "--no-photos")
    call_command("seed", "--no-photos")
    for slug in ("sharma", "patel"):
        tenant = Tenant.objects.get(slug=slug)
        with tenant_context(tenant.id):
            assert Order.objects.count() == 11, slug
            for tab, condition in TABS.items():
                assert Order.objects.filter(condition).exists(), (slug, tab)
            statuses = set(Order.objects.values_list("status", flat=True))
            assert statuses >= {"PLACED", "ON_HOLD", "ACCEPTED", "PACKED", "DISPATCHED"}
            assert {"COMPLETED", "REJECTED", "CANCELLED"} <= statuses
            assert Order.objects.filter(placed_via="STAFF", placed_by_label__endswith="(Sales)")
            assert BackorderAllocation.objects.filter(status="PROPOSED").count() == 1
            assert Order.objects.exclude(retailer_note="").exists()
        check_order_invariants(tenant)
