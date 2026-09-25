"""Authentication and session services (spec 5.2, ADR-020, ADR-025, ADR-026, ADR-030).

Rules that matter for security:
- Every credential failure returns the same ``INVALID_CREDENTIALS`` error: unknown email, wrong
  password, locked account, wrong host for the account type, or no access to the host's tenant.
- Failed attempts are counted in their own committed transaction (the API response is an error).
- Tokens are issued only for the host's tenant; the generic domain hands the session over to the
  tenant subdomain with a single-use code, so refresh cookies stay host-scoped.
"""

import hashlib
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import update_last_login
from django.db import transaction
from django.utils import timezone

from apps.accounts import selectors
from apps.accounts.models import HandoffCode, LoginChallenge, User
from apps.accounts.tokens import (
    IssuedTokens,
    SessionExpired,
    consume_refresh,
    issue_tokens,
    revoke_refresh,
    session_expiry_from,
)
from apps.audit import services as audit
from apps.platform.models import Tenant
from apps.platform.selectors import get_platform_setting, tenant_by_slug
from common import ratelimit
from common.authentication import TENANT_CLAIM
from common.error_codes import ErrorCode
from common.errors import DomainError
from common.hosts import HostContext, HostKind

logger = logging.getLogger(__name__)

_DUMMY_PASSWORD_HASH = make_password("timing-equaliser-for-unknown-accounts")


class InvalidCredentials(DomainError):
    status_code = 400
    code = ErrorCode.INVALID_CREDENTIALS
    default_message = (
        "The email or password is incorrect. After several failed attempts, sign-in is paused "
        "for a few minutes."
    )


class TenantSuspended(DomainError):
    status_code = 403
    code = ErrorCode.TENANT_SUSPENDED
    default_message = "This account is on hold. Please contact the platform support team."


class TokenInvalid(DomainError):
    status_code = 400
    code = ErrorCode.TOKEN_INVALID
    default_message = "This link or code has expired or was already used. Please start again."


class LoginStatus(StrEnum):
    AUTHENTICATED = "authenticated"
    HANDOFF = "handoff"
    CHOOSE_TENANT = "choose_tenant"


@dataclass(frozen=True)
class Handoff:
    code: str
    tenant_slug: str


@dataclass(frozen=True)
class LoginOutcome:
    status: LoginStatus
    user: User
    tokens: IssuedTokens | None = None
    handoff: Handoff | None = None
    choice_token: str | None = None
    tenants: list[Tenant] = field(default_factory=list)


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _new_secret() -> str:
    return secrets.token_urlsafe(32)


# --- Rate limits & lockout ------------------------------------------------------------------------


def _limit_login(email: str, ip: str | None) -> None:
    ratelimit.hit("login:ip", ip, get_platform_setting("platform.login_rate_per_ip_per_minute"), 60)
    ratelimit.hit(
        "login:email", email, get_platform_setting("platform.login_rate_per_email_per_minute"), 60
    )


def _register_failure(user_id: UUID) -> None:
    """Count a failed password in its own transaction; lock the account at the threshold."""
    from apps.accounts.tasks import send_account_locked_email

    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        if user.is_locked():
            return
        user.failed_login_count += 1
        if user.failed_login_count >= get_platform_setting("platform.login_lockout_threshold"):
            minutes = get_platform_setting("platform.login_lockout_minutes")
            user.locked_until = timezone.now() + timedelta(minutes=minutes)
            user.failed_login_count = 0
            audit.record(
                "auth.account_locked",
                target=user,
                tenant_id=None,
                metadata={"minutes": minutes},
            )
            transaction.on_commit(lambda: send_account_locked_email.delay(str(user_id)))
        user.save(update_fields=["failed_login_count", "locked_until"])


def _clear_failures(user: User) -> None:
    if user.failed_login_count or user.locked_until:
        User.objects.filter(pk=user.pk).update(failed_login_count=0, locked_until=None)
        user.failed_login_count, user.locked_until = 0, None


def verify_password_login(email: str, password: str, ip: str | None) -> User:
    """Check email + password with rate limits and lockout. Raises ``InvalidCredentials``."""
    email = (email or "").strip().lower()
    _limit_login(email, ip)
    user = (
        User.objects.filter(
            email=email, user_type__in=[User.UserType.STAFF, User.UserType.PLATFORM]
        ).first()
        if email
        else None
    )
    if user is None:
        User(password=_DUMMY_PASSWORD_HASH).check_password(password)  # equalise timing
        raise InvalidCredentials()
    if user.is_locked():
        raise InvalidCredentials()  # no password check while locked: nothing to learn
    if not user.check_password(password) or not user.is_active:
        if user.is_active:
            _register_failure(user.pk)
        raise InvalidCredentials()
    _clear_failures(user)
    return user


# --- Staff login (ADR-020) ----------------------------------------------------------------------


def _login_admin_host(user: User) -> LoginOutcome:
    if user.user_type != User.UserType.PLATFORM:
        raise InvalidCredentials()
    return _authenticated(user, None)


def _login_tenant_host(user: User, slug: str) -> LoginOutcome:
    if user.user_type != User.UserType.STAFF:
        raise InvalidCredentials()
    tenant = tenant_by_slug(slug)
    if tenant is None or selectors.active_membership(user, tenant.id) is None:
        raise InvalidCredentials()
    if tenant.status == Tenant.Status.SUSPENDED:
        raise TenantSuspended()
    if tenant.status != Tenant.Status.ACTIVE:
        raise InvalidCredentials()
    return _authenticated(user, tenant.id)


def _login_generic_host(user: User) -> LoginOutcome:
    if user.user_type != User.UserType.STAFF:
        raise InvalidCredentials()
    tenants = selectors.staff_memberships_for_login(user)
    if not tenants:
        if selectors.has_membership_in_suspended_tenant(user):
            raise TenantSuspended()
        raise InvalidCredentials()
    if len(tenants) == 1:
        return LoginOutcome(
            status=LoginStatus.HANDOFF, user=user, handoff=create_handoff(user, tenants[0])
        )
    raw = _new_secret()
    LoginChallenge.objects.create(
        kind=LoginChallenge.Kind.STAFF_TENANT_CHOICE,
        token_hash=token_hash(raw),
        user=user,
        candidates=[str(t.pk) for t in tenants],
        expires_at=timezone.now() + timedelta(seconds=settings.AUTH_CHALLENGE_TTL_SECONDS),
    )
    return LoginOutcome(
        status=LoginStatus.CHOOSE_TENANT, user=user, choice_token=raw, tenants=tenants
    )


def _authenticated(
    user: User, tenant_id: UUID | None, session_expires_at: datetime | None = None
) -> LoginOutcome:
    tokens = issue_tokens(user, tenant_id, session_expires_at=session_expires_at)
    update_last_login(User, user)
    logger.info("login succeeded", extra={"user_id": str(user.pk), "tenant": str(tenant_id)})
    return LoginOutcome(status=LoginStatus.AUTHENTICATED, user=user, tokens=tokens)


def staff_login(email: str, password: str, host: HostContext, ip: str | None) -> LoginOutcome:
    """Email + password sign-in for staff and super admins, following the host rules."""
    user = verify_password_login(email, password, ip)
    with transaction.atomic():
        if host.kind == HostKind.ADMIN:
            return _login_admin_host(user)
        if host.kind == HostKind.TENANT and host.tenant_slug:
            return _login_tenant_host(user, host.tenant_slug)
        if host.kind == HostKind.GENERIC:
            return _login_generic_host(user)
    raise InvalidCredentials()


# --- Tenant chooser & handoff ------------------------------------------------------------------


def _consume_challenge(raw: str, kind: str) -> LoginChallenge:
    """Mark a challenge used exactly once (conditional update), or raise ``TokenInvalid``."""
    now = timezone.now()
    digest = token_hash(raw or "")
    updated = LoginChallenge.objects.filter(
        token_hash=digest, kind=kind, used_at__isnull=True, expires_at__gt=now
    ).update(used_at=now)
    if updated != 1:
        raise TokenInvalid()
    challenge: LoginChallenge = LoginChallenge.objects.select_related("user").get(token_hash=digest)
    return challenge


@transaction.atomic
def choose_tenant(choice_token: str, tenant_id: UUID) -> Handoff:
    challenge = _consume_challenge(choice_token, LoginChallenge.Kind.STAFF_TENANT_CHOICE)
    user = challenge.user
    if user is None or not user.is_active or str(tenant_id) not in challenge.candidates:
        raise TokenInvalid()
    tenant = next(
        (t for t in selectors.staff_memberships_for_login(user) if t.pk == tenant_id), None
    )
    if tenant is None:
        raise TokenInvalid()
    return create_handoff(user, tenant)


def create_handoff(
    user: User, tenant: Tenant, session_expires_at: datetime | None = None
) -> Handoff:
    raw = _new_secret()
    HandoffCode.objects.create(
        code_hash=token_hash(raw),
        user=user,
        tenant=tenant,
        session_expires_at=session_expires_at,
        expires_at=timezone.now() + timedelta(seconds=settings.AUTH_HANDOFF_TTL_SECONDS),
    )
    return Handoff(code=raw, tenant_slug=tenant.slug)


@transaction.atomic
def exchange_handoff(code: str, host: HostContext, ip: str | None) -> LoginOutcome:
    """On the tenant subdomain: turn a handoff code into a session for that tenant."""
    ratelimit.hit(
        "handoff:ip", ip, get_platform_setting("platform.login_rate_per_ip_per_minute"), 60
    )
    now = timezone.now()
    digest = token_hash(code or "")
    updated = HandoffCode.objects.filter(
        code_hash=digest, used_at__isnull=True, expires_at__gt=now
    ).update(used_at=now)
    if updated != 1:
        raise TokenInvalid()
    handoff = HandoffCode.objects.select_related("user", "tenant").get(code_hash=digest)
    user, tenant = handoff.user, handoff.tenant
    if host.kind != HostKind.TENANT or host.tenant_slug != tenant.slug or not user.is_active:
        raise TokenInvalid()
    if tenant.status == Tenant.Status.SUSPENDED:
        raise TenantSuspended()
    if tenant.status != Tenant.Status.ACTIVE:
        raise TokenInvalid()
    if (
        user.user_type == User.UserType.STAFF
        and selectors.active_membership(user, tenant.id) is None
    ):
        raise TokenInvalid()
    return _authenticated(user, tenant.id, handoff.session_expires_at)


# --- Refresh & logout -------------------------------------------------------------------------


def refresh_session(raw_refresh: str) -> tuple[User, IssuedTokens]:
    """Rotate a refresh token: the old one is blacklisted, access is re-checked (ADR-025)."""
    token, outstanding = consume_refresh(raw_refresh)
    user = User.objects.filter(pk=outstanding.user_id).first() if outstanding.user_id else None
    if user is None or not user.is_active:
        raise SessionExpired()
    raw_tenant = token.get(TENANT_CLAIM)
    tenant_id = UUID(str(raw_tenant)) if raw_tenant else None
    if tenant_id is not None:
        tenant = Tenant.objects.filter(pk=tenant_id).first()  # tenant registry: no RLS
        if tenant is None:
            raise SessionExpired()
        if tenant.status == Tenant.Status.SUSPENDED:
            raise TenantSuspended()
        if (
            user.user_type == User.UserType.STAFF
            and selectors.active_membership(user, tenant_id) is None
        ):
            raise SessionExpired()
    with transaction.atomic():
        tokens = issue_tokens(user, tenant_id, session_expires_at=session_expiry_from(token))
    return user, tokens


def logout(raw_refresh: str | None) -> None:
    if raw_refresh:
        revoke_refresh(raw_refresh)


def purge_expired_login_records(older_than: timedelta = timedelta(days=1)) -> int:
    """Delete used/expired challenges and handoff codes (beat task)."""
    cutoff = timezone.now() - older_than
    a, _ = LoginChallenge.objects.filter(expires_at__lt=cutoff).delete()
    b, _ = HandoffCode.objects.filter(expires_at__lt=cutoff).delete()
    return a + b


# --- Profile ------------------------------------------------------------------------------------


def update_profile(
    user: User, *, full_name: str | None = None, preferred_language: str | None = None
) -> User:
    fields = []
    if full_name is not None:
        user.full_name = full_name.strip()
        fields.append("full_name")
    if preferred_language is not None:
        user.preferred_language = preferred_language
        fields.append("preferred_language")
    if fields:
        user.save(update_fields=fields)
    return user
