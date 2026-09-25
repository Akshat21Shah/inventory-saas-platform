import pytest
from django.core.cache import cache
from django.core.management import CommandError, call_command

from apps.accounts.models import User
from apps.accounts.tests.factories import make_super_admin
from common import ratelimit

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


def _exhaust(bucket: str, identifier: str, limit: int, window: int) -> None:
    for _ in range(limit):
        ratelimit.hit(bucket, identifier, limit, window)
    with pytest.raises(ratelimit.RateLimited):
        ratelimit.hit(bucket, identifier, limit, window)


def test_reset_clears_the_test_accounts_and_ip_counters_only(settings):
    settings.DEBUG = True
    admin = make_super_admin("root@platform.example.com")
    admin.failed_login_count, admin.totp_last_step = 4, 123
    admin.save(update_fields=["failed_login_count", "totp_last_step"])
    _exhaust("login:email", "root@platform.example.com", 5, 60)
    _exhaust("otp:phone", "+919876500001", 3, 600)
    _exhaust("otp:ip", "172.30.0.1", 100, 3600)
    _exhaust("login:email", "someone-else@example.com", 5, 60)

    call_command(
        "reset_e2e_limits", "--email", "Root@Platform.example.com", "--phone", "98765 00001"
    )

    ratelimit.hit("login:email", "root@platform.example.com", 5, 60)
    ratelimit.hit("otp:phone", "+919876500001", 3, 600)
    ratelimit.hit("otp:ip", "172.30.0.1", 100, 3600)
    with pytest.raises(ratelimit.RateLimited):  # other accounts keep their limits
        ratelimit.hit("login:email", "someone-else@example.com", 5, 60)
    fresh = User.objects.get(pk=admin.pk)
    assert (fresh.failed_login_count, fresh.totp_last_step) == (0, None)


def test_reset_refuses_outside_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("reset_e2e_limits", "--email", "root@platform.example.com")
