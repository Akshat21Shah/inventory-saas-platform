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
