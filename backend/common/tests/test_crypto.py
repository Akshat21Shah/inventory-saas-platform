from io import StringIO

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import connection

from common import crypto
from common.tests.testapp.models import SecretHolder

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_keys():
    crypto.reset_key_cache()
    yield
    crypto.reset_key_cache()


def _raw(pk):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT secret FROM {SecretHolder._meta.db_table} WHERE id = %s", [pk])  # noqa: S608
        return cursor.fetchone()[0]


def test_value_is_encrypted_at_rest_and_decrypted_on_read():
    holder = SecretHolder.objects.create(secret="123456789012")
    raw = _raw(holder.pk)
    assert raw != "123456789012"
    assert "123456789012" not in raw
    assert SecretHolder.objects.get(pk=holder.pk).secret == "123456789012"


def test_encryption_is_randomised():
    assert crypto.encrypt("same") != crypto.encrypt("same")


def test_empty_and_null_are_stored_as_is():
    holder = SecretHolder.objects.create(secret="", optional_secret=None)
    assert _raw(holder.pk) == ""
    fresh = SecretHolder.objects.get(pk=holder.pk)
    assert fresh.secret == ""
    assert fresh.optional_secret is None


def test_filtering_on_encrypted_field_is_refused():
    with pytest.raises(TypeError, match="does not support"):
        SecretHolder.objects.filter(secret="x").count()
    assert SecretHolder.objects.filter(optional_secret__isnull=True).count() == 0


def test_key_rotation_keeps_old_values_readable_and_command_reencrypts(settings):
    old_key = settings.FIELD_ENCRYPTION_KEYS[0]
    holder = SecretHolder.objects.create(secret="acct-001")
    before = _raw(holder.pk)

    new_key = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_KEYS = [new_key, old_key]
    crypto.reset_key_cache()
    assert SecretHolder.objects.get(pk=holder.pk).secret == "acct-001"

    call_command("rotate_encrypted_fields", stdout=StringIO())
    after = _raw(holder.pk)
    assert after != before

    settings.FIELD_ENCRYPTION_KEYS = [new_key]  # old key removed
    crypto.reset_key_cache()
    assert SecretHolder.objects.get(pk=holder.pk).secret == "acct-001"


def test_unknown_key_fails_loudly(settings):
    holder = SecretHolder.objects.create(secret="acct-002")
    settings.FIELD_ENCRYPTION_KEYS = [Fernet.generate_key().decode()]
    crypto.reset_key_cache()
    with pytest.raises(crypto.DecryptionError):
        SecretHolder.objects.get(pk=holder.pk)


def test_missing_or_invalid_keys_are_configuration_errors(settings):
    settings.FIELD_ENCRYPTION_KEYS = []
    crypto.reset_key_cache()
    with pytest.raises(ImproperlyConfigured):
        crypto.encrypt("x")
    settings.FIELD_ENCRYPTION_KEYS = ["not-a-fernet-key"]
    crypto.reset_key_cache()
    with pytest.raises(ImproperlyConfigured):
        crypto.encrypt("x")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("123456789012", "••••9012"), ("1234", "••••"), ("", ""), (None, "")],
)
def test_mask(value, expected):
    assert crypto.mask(value) == expected
