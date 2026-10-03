"""JWT issuance, rotation and revocation (ADR-025).

Refresh tokens are built here (not via ``RefreshToken.for_user``) so each user type gets its own
lifetime and the outstanding-token record matches the real expiry. Staff and super admin sessions
end at ``sess_exp`` (fixed at sign-in); retailer sessions slide.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.utils import datetime_from_epoch, get_md5_hash_password

from apps.accounts.models import User
from common.authentication import TENANT_CLAIM
from common.error_codes import ErrorCode
from common.errors import DomainError

USER_TYPE_CLAIM = "utype"
SESSION_EXPIRY_CLAIM = "sess_exp"


class SessionExpired(DomainError):
    status_code = 401
    code = ErrorCode.SESSION_EXPIRED
    default_message = gettext_lazy("Your session has ended. Please sign in again.")


@dataclass(frozen=True)
class IssuedTokens:
    access: str
    access_expires_at: datetime
    refresh: str
    refresh_expires_at: datetime
    session_expires_at: datetime | None


def refresh_lifetime(user: User) -> timedelta:
    lifetime: timedelta = settings.AUTH_REFRESH_LIFETIMES[user.user_type]
    return lifetime


def issue_tokens(
    user: User, tenant_id: UUID | None, *, session_expires_at: datetime | None = None
) -> IssuedTokens:
    """New refresh + access pair for ``user`` acting in ``tenant_id`` (None for platform users).

    ``session_expires_at``: the fixed end of a non-sliding session; computed from the user type's
    lifetime when a session starts. Sliding sessions (retailers) have none.
    """
    now = timezone.now()
    lifetime = refresh_lifetime(user)
    sliding = user.user_type in settings.AUTH_SLIDING_USER_TYPES
    if sliding:
        expires_at = now + lifetime
    else:
        session_expires_at = session_expires_at or now + lifetime
        expires_at = min(now + lifetime, session_expires_at)
    if expires_at <= now:
        raise SessionExpired()

    refresh = RefreshToken()
    refresh[api_settings.USER_ID_CLAIM] = str(user.pk)
    refresh[api_settings.REVOKE_TOKEN_CLAIM] = get_md5_hash_password(user.password)
    refresh[USER_TYPE_CLAIM] = user.user_type
    if tenant_id is not None:
        refresh[TENANT_CLAIM] = str(tenant_id)
    if session_expires_at is not None:
        refresh[SESSION_EXPIRY_CLAIM] = int(session_expires_at.timestamp())
    refresh.set_exp(from_time=now, lifetime=expires_at - now)
    OutstandingToken.objects.create(
        user=user,
        jti=refresh[api_settings.JTI_CLAIM],
        token=str(refresh),
        created_at=now,
        expires_at=datetime_from_epoch(refresh["exp"]),
    )
    access = refresh.access_token
    return IssuedTokens(
        access=str(access),
        access_expires_at=datetime_from_epoch(access["exp"]),
        refresh=str(refresh),
        refresh_expires_at=datetime_from_epoch(refresh["exp"]),
        session_expires_at=session_expires_at,
    )


def decode_refresh(raw: str) -> RefreshToken:
    """Signature, expiry and token type checked; raises ``SessionExpired`` otherwise."""
    try:
        return RefreshToken(raw)  # type: ignore[arg-type]
    except TokenError as exc:
        raise SessionExpired() from exc


@transaction.atomic
def consume_refresh(raw: str) -> tuple[RefreshToken, OutstandingToken]:
    """Validate a refresh token and blacklist it, exactly once even under concurrent use.

    The outstanding-token row is locked, so two simultaneous refreshes with the same token cannot
    both succeed (the loser sees it blacklisted).
    """
    token = decode_refresh(raw)
    jti = token[api_settings.JTI_CLAIM]
    outstanding = OutstandingToken.objects.select_for_update().filter(jti=jti).first()
    if outstanding is None or BlacklistedToken.objects.filter(token=outstanding).exists():
        raise SessionExpired()
    BlacklistedToken.objects.create(token=outstanding)
    return token, outstanding


def revoke_refresh(raw: str) -> None:
    """Blacklist a refresh token if it is valid (logout). Invalid tokens are ignored."""
    try:
        token = RefreshToken(raw)  # type: ignore[arg-type]
    except TokenError:
        return
    outstanding = OutstandingToken.objects.filter(jti=token[api_settings.JTI_CLAIM]).first()
    if outstanding is not None:
        BlacklistedToken.objects.get_or_create(token=outstanding)


def revoke_all_refresh_tokens(user: User) -> int:
    """Blacklist every outstanding refresh token of ``user`` (password change, deactivation)."""
    pending = list(
        OutstandingToken.objects.filter(user=user, expires_at__gt=timezone.now()).exclude(
            blacklistedtoken__isnull=False
        )
    )
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=t) for t in pending], ignore_conflicts=True
    )
    return len(pending)


def session_expiry_from(token: Any) -> datetime | None:
    value = token.get(SESSION_EXPIRY_CLAIM)
    return datetime_from_epoch(value) if value else None
