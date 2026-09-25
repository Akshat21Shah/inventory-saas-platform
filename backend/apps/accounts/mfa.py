"""TOTP (RFC 6238) and recovery codes for the second sign-in factor (spec 5.2)."""

import hashlib
import secrets
import time

import pyotp
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import RecoveryCode, User

TOTP_INTERVAL = 30
TOTP_DIGITS = 6
RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alikes (0/o, 1/l/i)


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, account_name: str) -> str:
    issuer: str = settings.TOTP_ISSUER
    return pyotp.TOTP(secret, interval=TOTP_INTERVAL, digits=TOTP_DIGITS).provisioning_uri(
        name=account_name, issuer_name=issuer
    )


def matching_step(secret: str, code: str, *, after_step: int | None = None) -> int | None:
    """The time step (±1 for clock drift) whose code matches, if newer than ``after_step``."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != TOTP_DIGITS or not code.isdigit() or not secret:
        return None
    totp = pyotp.TOTP(secret, interval=TOTP_INTERVAL, digits=TOTP_DIGITS)
    current = int(time.time()) // TOTP_INTERVAL
    for step in (current - 1, current, current + 1):
        if after_step is not None and step <= after_step:
            continue  # each code works once (replay protection)
        if secrets.compare_digest(totp.at(step * TOTP_INTERVAL), code):
            return step
    return None


def verify_user_totp(user: User, code: str) -> bool:
    """Check ``code`` against the user's enabled TOTP and consume its time step."""
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        if not locked.totp_enabled:
            return False
        step = matching_step(locked.totp_secret, code, after_step=locked.totp_last_step)
        if step is None:
            return False
        User.objects.filter(pk=user.pk).update(totp_last_step=step)
        user.totp_last_step = step
    return True


def _hash(code: str) -> str:
    normalised = code.strip().lower().replace("-", "").replace(" ", "")
    return hashlib.sha256(normalised.encode()).hexdigest()


def _new_recovery_code() -> str:
    raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(16))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:]}"


def replace_recovery_codes(user: User) -> list[str]:
    """Issue a fresh set of recovery codes (old ones stop working). Returns the plaintext once."""
    codes = [_new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    RecoveryCode.objects.filter(user=user).delete()
    RecoveryCode.objects.bulk_create([RecoveryCode(user=user, code_hash=_hash(c)) for c in codes])
    return codes


def use_recovery_code(user: User, code: str) -> bool:
    updated = RecoveryCode.objects.filter(
        user=user, code_hash=_hash(code or ""), used_at__isnull=True
    ).update(used_at=timezone.now())
    return updated == 1


def verify_second_factor(user: User, code: str | None, recovery_code: str | None) -> bool:
    if code:
        return verify_user_totp(user, code)
    if recovery_code:
        return use_recovery_code(user, recovery_code)
    return False


def remaining_recovery_codes(user: User) -> int:
    return RecoveryCode.objects.filter(user=user, used_at__isnull=True).count()
