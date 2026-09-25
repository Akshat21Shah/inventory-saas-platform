"""The public dev 2FA key (``manage.py seed``) can never be used or kept outside DEBUG."""

import pyotp
import pytest
from django.core.management import CommandError, call_command

from apps.accounts import mfa
from apps.accounts.checks import dev_totp_key_check
from apps.accounts.tests.factories import make_super_admin

pytestmark = pytest.mark.django_db


def _current_code() -> str:
    return pyotp.TOTP(mfa.DEV_TOTP_SECRET).now()


def test_the_dev_key_never_matches_outside_debug(settings):
    settings.DEBUG = False
    assert mfa.matching_step(mfa.DEV_TOTP_SECRET, _current_code()) is None


def test_the_dev_key_works_in_debug_only(settings):
    settings.DEBUG = True
    assert mfa.matching_step(mfa.DEV_TOTP_SECRET, _current_code()) is not None


def test_signing_in_with_the_dev_key_fails_outside_debug(settings):
    settings.DEBUG = False
    admin = make_super_admin("root@platform.example.com")
    admin.totp_secret, admin.totp_enabled = mfa.DEV_TOTP_SECRET, True
    admin.save(update_fields=["totp_secret", "totp_enabled"])
    assert mfa.verify_user_totp(admin, _current_code()) is False


def test_deploy_check_fails_while_any_account_has_the_dev_key(settings):
    settings.DEBUG = False
    admin = make_super_admin("root@platform.example.com")
    assert dev_totp_key_check(None, databases=["default"]) == []
    admin.totp_secret, admin.totp_enabled = mfa.DEV_TOTP_SECRET, True
    admin.save(update_fields=["totp_secret", "totp_enabled"])
    assert [e.id for e in dev_totp_key_check(None, databases=["default"])] == ["accounts.E003"]
    # Without database access (plain `check`), or in DEBUG, the check does not query.
    assert dev_totp_key_check(None, databases=None) == []
    settings.DEBUG = True
    assert dev_totp_key_check(None, databases=["default"]) == []


def test_the_seed_that_sets_the_key_refuses_outside_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed", "--reset-admin-2fa")


def test_deploy_check_reports_secrets_encrypted_with_other_keys(settings):
    """E.g. a development database opened with production keys: reported, not a crash."""
    from cryptography.fernet import Fernet

    from common import crypto

    settings.DEBUG = False
    admin = make_super_admin("root@platform.example.com")
    admin.totp_secret, admin.totp_enabled = pyotp.random_base32(), True
    admin.save(update_fields=["totp_secret", "totp_enabled"])
    settings.FIELD_ENCRYPTION_KEYS = [Fernet.generate_key().decode()]
    crypto.reset_key_cache()
    try:
        assert [e.id for e in dev_totp_key_check(None, databases=["default"])] == ["accounts.E004"]
    finally:
        crypto.reset_key_cache()
