"""Field-level encryption for secrets at rest (ADR-031).

Values are encrypted with ``MultiFernet``: the first key in ``FIELD_ENCRYPTION_KEYS`` encrypts and
every key decrypts, so keys can be rotated (add a new first key, run ``rotate_encrypted_fields``,
then drop the old key). Encrypted columns cannot be searched, filtered or indexed.
"""

from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models.expressions import Expression


class DecryptionError(Exception):
    """Stored ciphertext could not be decrypted with any configured key."""


@lru_cache(maxsize=1)
def _fernet() -> MultiFernet:
    keys: list[str] = list(getattr(settings, "FIELD_ENCRYPTION_KEYS", []) or [])
    if not keys:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS is not configured")
    try:
        return MultiFernet([Fernet(key.encode()) for key in keys])
    except ValueError as exc:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS contains an invalid Fernet key") from exc


def reset_key_cache() -> None:
    """For tests that change FIELD_ENCRYPTION_KEYS."""
    _fernet.cache_clear()


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError("ciphertext could not be decrypted with the configured keys") from exc


def rotate(token: str) -> str:
    """Re-encrypt ``token`` with the current primary key."""
    try:
        return _fernet().rotate(token.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError("ciphertext could not be decrypted with the configured keys") from exc


def mask(value: str | None, visible: int = 4) -> str:
    """``"123456789012"`` → ``"••••9012"``. Used for API responses and audit diffs."""
    if not value:
        return ""
    return "••••" + value[-visible:] if len(value) > visible else "••••"


class EncryptedTextField(models.TextField):  # type: ignore[type-arg]
    """Text stored encrypted. Empty string and NULL are stored as-is (nothing to protect)."""

    description = "Encrypted text"

    def from_db_value(
        self, value: str | None, expression: Expression, connection: BaseDatabaseWrapper
    ) -> str | None:
        if value is None or value == "":
            return value
        return decrypt(value)

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        return encrypt(str(value))

    def get_lookup(self, lookup_name: str) -> Any:
        if lookup_name not in ("isnull",):
            raise TypeError(f"EncryptedTextField does not support the '{lookup_name}' lookup")
        return super().get_lookup(lookup_name)
