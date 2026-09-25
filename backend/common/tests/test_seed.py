import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import User
from apps.platform.models import Tenant

pytestmark = pytest.mark.django_db


def test_seed_is_idempotent(settings):
    settings.DEBUG = True
    call_command("seed")
    call_command("seed")
    assert User.objects.filter(email="admin@platform.local", is_superuser=True).count() == 1
    assert set(Tenant.objects.values_list("slug", flat=True)) == {"sharma", "patel"}


def test_seed_refuses_without_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed")
