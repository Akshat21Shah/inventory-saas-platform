"""Deployment checks: refuse mock integrations in a deployed environment."""

from typing import Any

from django.conf import settings
from django.core.checks import CheckMessage, Error, Tags, register


@register(Tags.security, deploy=True)
def mock_integrations_check(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    errors: list[CheckMessage] = []
    if settings.SMS_PROVIDER == "mock" and not settings.ALLOW_MOCK_INTEGRATIONS:
        errors.append(
            Error("SMS_PROVIDER is 'mock' in a deployed environment.", id="accounts.E001")
        )
    if settings.OTP_FIXED_CODE:
        errors.append(
            Error("OTP_FIXED_CODE must not be set in a deployed environment.", id="accounts.E002")
        )
    return errors


@register(Tags.security, deploy=True)
def dev_totp_key_check(
    app_configs: Any, databases: Any = None, **kwargs: Any
) -> list[CheckMessage]:
    """accounts.E003: the public dev 2FA key must never exist outside DEBUG. Needs the database,
    so it runs with ``check --deploy --database default`` (the production image does this at
    startup). The key is encrypted at rest, so enabled secrets are decrypted and compared."""
    if settings.DEBUG or not databases or "default" not in databases:
        return []
    from django.db.models import F, TextField
    from django.db.models.functions import Cast

    from apps.accounts.mfa import DEV_TOTP_SECRET
    from apps.accounts.models import User
    from common.crypto import DecryptionError, decrypt

    # Read the ciphertext without the field's converter, so one bad value is reported, not raised.
    stored = (
        User.objects.filter(totp_enabled=True)
        .annotate(raw=Cast(F("totp_secret"), TextField()))
        .values_list("raw", flat=True)
    )
    undecryptable = 0
    for ciphertext in stored.iterator():
        if not ciphertext:
            continue
        try:
            secret = decrypt(ciphertext)
        except DecryptionError:
            undecryptable += 1
            continue
        if secret == DEV_TOTP_SECRET:
            return [
                Error(
                    "An account uses the public dev 2FA key outside DEBUG.",
                    hint="Reset that account's 2FA; never load `manage.py seed` data into this "
                    "environment.",
                    id="accounts.E003",
                )
            ]
    if undecryptable:
        return [
            Error(
                f"{undecryptable} 2FA secret(s) cannot be decrypted with FIELD_ENCRYPTION_KEYS.",
                hint="The data was encrypted with other keys (for example a development database).",
                id="accounts.E004",
            )
        ]
    return []
