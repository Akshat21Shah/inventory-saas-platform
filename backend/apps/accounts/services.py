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
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import update_last_login
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.translation import gettext, gettext_lazy

from apps.accounts import mfa, selectors
from apps.accounts.models import HandoffCode, LoginChallenge, RecoveryCode, User
from apps.accounts.tokens import (
    IssuedTokens,
    SessionExpired,
    consume_refresh,
    issue_tokens,
    revoke_all_refresh_tokens,
    revoke_refresh,
    session_expiry_from,
)
from apps.audit import services as audit
from apps.platform.models import Tenant
from apps.platform.selectors import get_platform_setting, get_setting, tenant_by_slug
from common import ratelimit
from common.authentication import TENANT_CLAIM
from common.context import Actor
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields
from common.hosts import HostContext, HostKind, web_url

logger = logging.getLogger(__name__)

_DUMMY_PASSWORD_HASH = make_password("timing-equaliser-for-unknown-accounts")


class InvalidCredentials(DomainError):
    status_code = 400
    code = ErrorCode.INVALID_CREDENTIALS
    default_message = gettext_lazy(
        "The email or password is incorrect. After several failed attempts, sign-in is paused "
        "for a few minutes."
    )


class RetailerOnHold(DomainError):
    """ADR-036: the distributor put this shop on hold and doesn't let such shops sign in."""

    status_code = 403
    code = ErrorCode.RETAILER_ON_HOLD
    default_message = gettext_lazy("Your account is on hold. Please contact your distributor.")


def refuse_if_on_hold(phone: str, tenant_id: UUID) -> None:
    if selectors.retailer_on_hold_refused(phone, tenant_id):
        raise RetailerOnHold()


class TenantUnavailable(DomainError):
    """One neutral answer for every tenant that is not ACTIVE (onboarding, suspended, ...): the
    specific state is never disclosed outside the platform team."""

    status_code = 403
    code = ErrorCode.TENANT_UNAVAILABLE
    default_message = gettext_lazy(
        "This account is currently unavailable. Please contact your distributor."
    )


class TokenInvalid(DomainError):
    status_code = 400
    code = ErrorCode.TOKEN_INVALID
    default_message = gettext_lazy(
        "This link or code has expired or was already used. Please start again."
    )


class LoginStatus(StrEnum):
    AUTHENTICATED = "authenticated"
    HANDOFF = "handoff"
    CHOOSE_TENANT = "choose_tenant"
    MFA_REQUIRED = "mfa_required"
    MFA_SETUP_REQUIRED = "mfa_setup_required"
    CHOOSE_ACCOUNT = "choose_account"  # retailer: pick a distributor (ADR-015)


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
    mfa_token: str | None = None
    enrolment_token: str | None = None
    recovery_codes: list[str] = field(default_factory=list)
    accounts: list[Any] = field(default_factory=list)  # selectors.RetailerAccount


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _new_secret() -> str:
    return secrets.token_urlsafe(32)


# --- Rate limits & lockout ----------------------------------------------------------------------


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


def verify_password_login(
    email: str, password: str, ip: str | None, *, rate_limited: bool = False
) -> User:
    """Check email + password with rate limits and lockout. Raises ``InvalidCredentials``."""
    email = (email or "").strip().lower()
    if not rate_limited:
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
#
# After the password check the login continues to a *target*: tokens for this host's tenant (or
# for the platform on the admin host), or the generic-domain handoff/chooser. A second factor
# (verification, or enrolment where it is required) sits between the password and the target.
# The target travels in the challenge payload, bound to the host that started the login.


def _tokens_target(
    host: HostContext, tenant_id: UUID | None, session_expires_at: datetime | None = None
) -> dict[str, Any]:
    return {
        "next": "tokens",
        "tenant_id": str(tenant_id) if tenant_id else None,
        "host_kind": host.kind.value,
        "host_slug": host.tenant_slug,
        "session_expires_at": session_expires_at.isoformat() if session_expires_at else None,
    }


def _target_for_host(user: User, host: HostContext) -> dict[str, Any]:
    """Apply the host rules; raise the generic error when this host is not for this account."""
    if host.kind == HostKind.ADMIN and user.user_type == User.UserType.PLATFORM:
        return _tokens_target(host, None)
    if host.kind == HostKind.TENANT and host.tenant_slug and user.user_type == User.UserType.STAFF:
        tenant = tenant_by_slug(host.tenant_slug)
        if tenant is None or selectors.active_membership(user, tenant.id) is None:
            raise InvalidCredentials()
        if tenant.status != Tenant.Status.ACTIVE:
            raise TenantUnavailable()
        return _tokens_target(host, tenant.id)
    if host.kind == HostKind.GENERIC and user.user_type == User.UserType.STAFF:
        if not selectors.staff_memberships_for_login(user):
            if selectors.has_membership_in_unavailable_tenant(user):
                raise TenantUnavailable()
            raise InvalidCredentials()
        return {"next": "generic", "host_kind": host.kind.value, "host_slug": None}
    raise InvalidCredentials()


def _mfa_enrolment_required(user: User, target: dict[str, Any]) -> bool:
    """Super admins always need 2FA; staff when the target tenant requires it (ADR-030)."""
    if user.totp_enabled:
        return False
    if user.user_type == User.UserType.PLATFORM:
        return True
    if user.user_type != User.UserType.STAFF:
        return False  # retailers sign in with a one-time code; the staff policy is not theirs
    tenant_id = target.get("tenant_id")
    return bool(tenant_id) and bool(get_setting("security.require_staff_2fa", UUID(tenant_id)))


def _challenge(kind: str, user: User, target: dict[str, Any]) -> str:
    raw = _new_secret()
    LoginChallenge.objects.create(
        kind=kind,
        token_hash=token_hash(raw),
        user=user,
        payload=target,
        expires_at=timezone.now() + timedelta(seconds=settings.AUTH_CHALLENGE_TTL_SECONDS),
    )
    return raw


def _continue_login(
    user: User, target: dict[str, Any], *, factor_verified: bool = False
) -> LoginOutcome:
    if user.totp_enabled and not factor_verified:
        raw = _challenge(LoginChallenge.Kind.MFA, user, target)
        return LoginOutcome(status=LoginStatus.MFA_REQUIRED, user=user, mfa_token=raw)
    if _mfa_enrolment_required(user, target):
        raw = _challenge(LoginChallenge.Kind.MFA_ENROLMENT, user, target)
        return LoginOutcome(status=LoginStatus.MFA_SETUP_REQUIRED, user=user, enrolment_token=raw)
    return _complete_login(user, target)


def _complete_login(user: User, target: dict[str, Any]) -> LoginOutcome:
    if target["next"] == "generic":
        return _generic_outcome(user)
    tenant_id = UUID(target["tenant_id"]) if target.get("tenant_id") else None
    raw_expiry = target.get("session_expires_at")
    return _authenticated(
        user, tenant_id, datetime.fromisoformat(raw_expiry) if raw_expiry else None
    )


def _generic_outcome(user: User) -> LoginOutcome:
    tenants = selectors.staff_memberships_for_login(user)
    if not tenants:
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


def ensure_host_tenant_available(host: HostContext) -> None:
    """On a tenant subdomain whose tenant is not ACTIVE, every sign-in attempt gets the same
    neutral answer, before any credential is checked (the pre-login page shows it too)."""
    if host.kind == HostKind.TENANT and host.tenant_slug:
        tenant = tenant_by_slug(host.tenant_slug)
        if tenant is not None and tenant.status != Tenant.Status.ACTIVE:
            raise TenantUnavailable()


def staff_login(email: str, password: str, host: HostContext, ip: str | None) -> LoginOutcome:
    """Email + password sign-in for staff and super admins, following the host rules."""
    _limit_login((email or "").strip().lower(), ip)
    ensure_host_tenant_available(host)
    user = verify_password_login(email, password, ip, rate_limited=True)
    with transaction.atomic():
        return _continue_login(user, _target_for_host(user, host))


def _check_challenge_host(target: dict[str, Any], host: HostContext) -> None:
    """A login continues only on the host that started it (cookies are host-scoped)."""
    if target.get("host_kind") != host.kind.value or target.get("host_slug") != host.tenant_slug:
        raise TokenInvalid()


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
    user: User,
    tenant: Tenant,
    session_expires_at: datetime | None = None,
    impersonation_session_id: UUID | None = None,
) -> Handoff:
    raw = _new_secret()
    HandoffCode.objects.create(
        code_hash=token_hash(raw),
        user=user,
        tenant=tenant,
        session_expires_at=session_expires_at,
        impersonation_session_id=impersonation_session_id,
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
    if tenant.status != Tenant.Status.ACTIVE and handoff.impersonation_session_id is None:
        raise TenantUnavailable()  # ADR-018: support may still look at a suspended tenant
    if (
        user.user_type == User.UserType.STAFF
        and selectors.active_membership(user, tenant.id) is None
    ):
        raise TokenInvalid()
    if user.user_type == User.UserType.RETAILER and (
        user.tenant_id != tenant.id
        or selectors.retailer_login_for_tenant(user.phone or "", tenant.id) is None
    ):
        refuse_if_on_hold(user.phone or "", tenant.id)
        raise TokenInvalid()
    if handoff.impersonation_session_id is not None:
        from apps.accounts.impersonation import complete_handoff

        return complete_handoff(handoff)
    # The second factor (if enabled) was verified on the generic domain before the handoff; the
    # tenant's own 2FA policy is applied here, where the tenant is known.
    target = _tokens_target(host, tenant.id, handoff.session_expires_at)
    return _continue_login(user, target, factor_verified=True)


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
        if tenant.status != Tenant.Status.ACTIVE:
            raise TenantUnavailable()
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
    user: User,
    *,
    full_name: str | None = None,
    preferred_language: str | None = None,
    allowed_languages: tuple[str, ...] = (),
) -> User:
    """A person's name and language. The language must be one they may choose
    (``allowed_languages``, ADR-060 item 12); a shop's login also sets its shop's language, which
    its messages and documents follow."""
    fields = []
    if full_name is not None:
        user.full_name = full_name.strip()
        fields.append("full_name")
    if preferred_language is not None:
        if preferred_language not in allowed_languages:
            raise InvalidFields(
                {"preferred_language": [gettext("This language isn't available. Choose another.")]}
            )
        user.preferred_language = preferred_language
        fields.append("preferred_language")
        if user.user_type == User.UserType.RETAILER:
            from apps.retailers.models import RetailerUser

            link = RetailerUser.objects.filter(user=user).select_related("retailer").first()
            if link is not None:
                link.retailer.preferred_language = preferred_language
                link.retailer.save(update_fields=["preferred_language", "updated_at"])
    if fields:
        user.save(update_fields=fields)
    return user


# --- Second factor (spec 5.2, ADR-030) ---------------------------------------------------------


class MfaInvalidCode(DomainError):
    status_code = 400
    code = ErrorCode.MFA_INVALID_CODE
    default_message = gettext_lazy(
        "That code didn't work. Check your authenticator app and try again."
    )


class MfaRequiredByPolicy(DomainError):
    status_code = 400
    code = ErrorCode.MFA_REQUIRED_BY_POLICY
    default_message = gettext_lazy(
        "Two-step verification is required for your account and can't be turned off."
    )


def _open_challenge(raw: str, kinds: tuple[str, ...]) -> LoginChallenge:
    challenge: LoginChallenge | None = (
        LoginChallenge.objects.select_related("user")
        .filter(
            token_hash=token_hash(raw or ""),
            kind__in=kinds,
            used_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .first()
    )
    if challenge is None or challenge.user is None or not challenge.user.is_active:
        raise TokenInvalid()
    return challenge


def _failed_code(challenge: LoginChallenge) -> None:
    """Count a wrong code (committed); the challenge dies after the allowed attempts."""
    limit = get_platform_setting("platform.otp_max_verify_attempts")
    with transaction.atomic():
        attempts = challenge.attempts + 1
        LoginChallenge.objects.filter(pk=challenge.pk).update(
            attempts=attempts, used_at=timezone.now() if attempts >= limit else None
        )
    raise MfaInvalidCode()


def _mark_used(challenge: LoginChallenge) -> None:
    if (
        LoginChallenge.objects.filter(pk=challenge.pk, used_at__isnull=True).update(
            used_at=timezone.now()
        )
        != 1
    ):
        raise TokenInvalid()


def verify_login_mfa(
    mfa_token: str, code: str | None, recovery_code: str | None, host: HostContext, ip: str | None
) -> LoginOutcome:
    """Second step of a sign-in with 2FA enabled (TOTP code or a recovery code)."""
    ratelimit.hit("mfa:ip", ip, get_platform_setting("platform.login_rate_per_ip_per_minute"), 60)
    challenge = _open_challenge(mfa_token, (LoginChallenge.Kind.MFA,))
    _check_challenge_host(challenge.payload, host)
    user = challenge.user
    assert user is not None
    if not mfa.verify_second_factor(user, code, recovery_code):
        _failed_code(challenge)
    with transaction.atomic():
        _mark_used(challenge)
        if recovery_code and not code:
            audit.record("auth.recovery_code_used", target=user, tenant_id=None, actor=_actor(user))
        return _complete_login(user, challenge.payload)


def _actor(user: User) -> Actor:
    return Actor(user_id=user.pk, actor_type=user.user_type)


def begin_enrolment(enrolment_token: str) -> tuple[str, str]:
    """Sign-in enrolment: a new TOTP secret for the user to add to their authenticator app."""
    challenge = _open_challenge(
        enrolment_token, (LoginChallenge.Kind.MFA_ENROLMENT, LoginChallenge.Kind.MFA_SETUP)
    )
    secret = mfa.new_secret()
    LoginChallenge.objects.filter(pk=challenge.pk).update(secret=secret)  # encrypted at rest
    user = challenge.user
    assert user is not None
    return secret, mfa.provisioning_uri(secret, user.email or str(user.pk))


def begin_mfa_setup(user: User) -> tuple[str, str, str]:
    """Account security page: returns ``(setup_token, secret, otpauth_uri)``."""
    if user.totp_enabled:
        raise InvalidFields({"code": [gettext("Two-step verification is already on.")]})
    raw = _challenge(LoginChallenge.Kind.MFA_SETUP, user, {})
    secret, uri = begin_enrolment(raw)
    return raw, secret, uri


def _first_code_step(challenge: LoginChallenge, code: str) -> int:
    """The time step of the first code from the app. A wrong code is counted in its own committed
    transaction, so call this outside any enclosing transaction."""
    step = mfa.matching_step(challenge.secret, code)
    if step is None:
        _failed_code(challenge)
    assert step is not None
    return step


@transaction.atomic
def _enable_totp(challenge: LoginChallenge, step: int) -> tuple[User, list[str]]:
    """Turn 2FA on (the code was already checked)."""
    user = challenge.user
    assert user is not None
    _mark_used(challenge)
    User.objects.filter(pk=user.pk).update(
        totp_secret=challenge.secret, totp_enabled=True, totp_last_step=step
    )
    user.refresh_from_db()
    codes = mfa.replace_recovery_codes(user)
    audit.record("auth.mfa_enabled", target=user, tenant_id=None, actor=_actor(user))
    return user, codes


def confirm_enrolment(token: str, code: str, host: HostContext) -> LoginOutcome:
    """2FA set-up required at sign-in: turn it on, then finish the login."""
    challenge = _open_challenge(token, (LoginChallenge.Kind.MFA_ENROLMENT,))
    _check_challenge_host(challenge.payload, host)
    user, codes = _enable_totp(challenge, _first_code_step(challenge, code))
    # Finishing the login may read memberships through the platform alias, so the 2FA change is
    # committed first (that connection cannot see this request's uncommitted rows).
    return replace(_complete_login(user, challenge.payload), recovery_codes=codes)


def confirm_setup(token: str, code: str) -> list[str]:
    """2FA set-up from "My account" (already signed in): turn it on; returns recovery codes."""
    challenge = _open_challenge(token, (LoginChallenge.Kind.MFA_SETUP,))
    _user, codes = _enable_totp(challenge, _first_code_step(challenge, code))
    return codes


def limit_mfa_management(user: User) -> None:
    """Managing 2FA needs a session; still cap guesses at the second factor per account."""
    ratelimit.hit("mfa-manage:user", str(user.pk), 5, 60)


def mfa_required_for(user: User, tenant_id: UUID | None) -> bool:
    if user.user_type == User.UserType.PLATFORM:
        return True
    return tenant_id is not None and bool(get_setting("security.require_staff_2fa", tenant_id))


def _check_password_and_factor(
    user: User, password: str, code: str | None, recovery_code: str | None
) -> None:
    if not user.check_password(password):
        raise InvalidFields({"password": [gettext("The password is incorrect.")]})
    if not mfa.verify_second_factor(user, code, recovery_code):
        raise MfaInvalidCode()


@transaction.atomic
def disable_mfa(
    user: User, password: str, code: str | None, recovery_code: str | None, tenant_id: UUID | None
) -> None:
    if mfa_required_for(user, tenant_id):
        raise MfaRequiredByPolicy()
    if not user.totp_enabled:
        return
    _check_password_and_factor(user, password, code, recovery_code)
    User.objects.filter(pk=user.pk).update(totp_secret="", totp_enabled=False, totp_last_step=None)
    RecoveryCode.objects.filter(user=user).delete()
    audit.record("auth.mfa_disabled", target=user, tenant_id=None)


@transaction.atomic
def regenerate_recovery_codes(
    user: User, password: str, code: str | None, recovery_code: str | None
) -> list[str]:
    if not user.totp_enabled:
        raise InvalidFields({"code": [gettext("Two-step verification is off.")]})
    _check_password_and_factor(user, password, code, recovery_code)
    codes = mfa.replace_recovery_codes(user)
    audit.record("auth.recovery_codes_regenerated", target=user, tenant_id=None)
    return codes


# --- Passwords ----------------------------------------------------------------------------------


def request_password_reset(email: str, ip: str | None) -> None:
    """Email a reset link if an active staff/super-admin account exists. Always looks the same."""
    from apps.accounts.tasks import send_password_reset_email

    email = (email or "").strip().lower()
    ratelimit.hit("reset:ip", ip, get_platform_setting("platform.login_rate_per_ip_per_minute"), 60)
    ratelimit.hit(
        "reset:email",
        email,
        get_platform_setting("platform.password_reset_per_email_per_hour"),
        3600,
    )
    user = User.objects.filter(
        email=email,
        is_active=True,
        user_type__in=[User.UserType.STAFF, User.UserType.PLATFORM],
    ).first()
    if user is not None:
        transaction.on_commit(lambda: send_password_reset_email.delay(str(user.pk)))


def _validated_new_password(user: User, new_password: str) -> None:
    try:
        validate_password(new_password, user)
    except DjangoValidationError as exc:
        raise InvalidFields({"new_password": list(exc.messages)}) from exc


@transaction.atomic
def reset_password(uidb64: str, token: str, new_password: str) -> None:
    """Set a new password from an emailed link. Unlocks the account and ends every session."""
    try:
        user_id = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.select_for_update().get(pk=user_id, is_active=True)
    except (ValueError, TypeError, OverflowError, User.DoesNotExist, DjangoValidationError) as exc:
        raise TokenInvalid() from exc
    if user.user_type == User.UserType.RETAILER or not default_token_generator.check_token(
        user, token
    ):
        raise TokenInvalid()
    _validated_new_password(user, new_password)
    user.set_password(new_password)
    user.failed_login_count, user.locked_until = 0, None
    user.save(update_fields=["password", "failed_login_count", "locked_until"])
    revoke_all_refresh_tokens(user)
    audit.record("auth.password_reset", target=user, tenant_id=None, actor=_actor(user))


@transaction.atomic
def change_password(
    user: User, current_password: str, new_password: str, tenant_id: UUID | None
) -> IssuedTokens:
    """Change the password; every other session ends, this one continues with new tokens."""
    if not user.check_password(current_password):
        raise InvalidFields({"current_password": [gettext("The current password is incorrect.")]})
    _validated_new_password(user, new_password)
    user.set_password(new_password)
    user.save(update_fields=["password"])
    revoke_all_refresh_tokens(user)
    audit.record("auth.password_changed", target=user, tenant_id=None)
    return issue_tokens(user, tenant_id)


def password_reset_link(user: User) -> str:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return web_url(f"/reset-password/{uid}/{token}", admin=user.user_type == User.UserType.PLATFORM)
