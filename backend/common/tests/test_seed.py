import pyotp
import pytest
from django.core.management import CommandError, call_command

from apps.accounts import mfa
from apps.accounts.models import Membership, User
from apps.platform.models import Tenant
from apps.retailers.models import Retailer
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


def test_seed_is_idempotent(settings):
    settings.DEBUG = True
    call_command("seed")
    call_command("seed")
    assert User.objects.filter(email="admin@platform.local", is_superuser=True).count() == 1
    assert set(Tenant.objects.values_list("slug", flat=True)) == {"sharma", "patel"}
    sharma = Tenant.objects.get(slug="sharma")
    with tenant_context(sharma.id):
        roles = set(Membership.objects.values_list("role__code", flat=True))
        assert roles == {"OWNER", "MANAGER", "SALES", "WAREHOUSE", "ACCOUNTS"}
        assert Retailer.objects.count() == 2
    owner = User.objects.get(email="owner@sharma.example.com")
    assert owner.check_password("staff-dev-password")
    # The shared shop phone has a login under both distributors (sign-in chooser).
    assert User.objects.filter(phone="+919876500000", user_type=User.UserType.RETAILER).count() == 2
    admin = User.objects.get(email="admin@platform.local")
    assert admin.totp_enabled
    assert mfa.matching_step(admin.totp_secret, pyotp.TOTP(admin.totp_secret).now()) is not None


def test_seed_keeps_an_existing_admin_2fa_key(settings):
    settings.DEBUG = True
    call_command("seed")
    admin = User.objects.get(email="admin@platform.local")
    admin.totp_secret = pyotp.random_base32()
    admin.save(update_fields=["totp_secret"])
    call_command("seed")
    admin.refresh_from_db()
    assert admin.totp_secret != "DEVSEEDADMINTOTPKEYDEVSEEDADMIN2"


def test_seed_refuses_without_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed")


def test_seed_can_put_the_admin_back_on_the_dev_2fa_key(settings):
    settings.DEBUG = True
    call_command("seed")
    admin = User.objects.get(email="admin@platform.local")
    admin.totp_secret = pyotp.random_base32()
    admin.save(update_fields=["totp_secret"])
    call_command("seed", "--reset-admin-2fa")
    admin.refresh_from_db()
    assert admin.totp_secret == "DEVSEEDADMINTOTPKEYDEVSEEDADMIN2"
