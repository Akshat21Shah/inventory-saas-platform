"""Retailer sign-in with a mobile number and a one-time code (spec 5.2, ADR-015, ADR-020).

- On a distributor's subdomain the code is sent only if that distributor has an active retailer with
  the number; on the generic domain, if any active distributor does.
- The request response is identical either way, and a verify for an unknown number fails exactly
  like a wrong code, so nothing reveals whether a number is registered anywhere.
- On the generic domain, after the code is verified, the phone's owner chooses among their
  distributors (ADR-015); the session then moves to that subdomain with a handoff code.
"""

import hashlib
import secrets
from contextlib import AbstractContextManager, nullcontext
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts import selectors
from apps.accounts.models import LoginChallenge, OTPRequest, User
from apps.accounts.services import (
    Handoff,
    LoginOutcome,
    LoginStatus,
    TenantUnavailable,
    TokenInvalid,
    _authenticated,
    _consume_challenge,
    _new_secret,
    create_handoff,
    refuse_if_on_hold,
    token_hash,
)
from apps.platform.models import Tenant
from apps.platform.selectors import get_platform_setting, tenant_by_slug
from common import ratelimit
from common.error_codes import ErrorCode
from common.errors import DomainError
from common.hosts import HostContext, HostKind
from common.tenancy import tenant_context


class OtpInvalid(DomainError):
    status_code = 400
    code = ErrorCode.OTP_INVALID
    default_message = "That code is wrong or has expired. Request a new code."


def _hash_code(phone: str, code: str) -> str:
    return hashlib.sha256(f"{phone}:{code}".encode()).hexdigest()


def _new_code() -> str:
    fixed = settings.OTP_FIXED_CODE if settings.ALLOW_MOCK_INTEGRATIONS else None
    return fixed or f"{secrets.randbelow(1_000_000):06d}"


def _scope(host: HostContext) -> Tenant | None:
    """The tenant of a subdomain request, None on the generic domain; other hosts are refused."""
    if host.kind == HostKind.TENANT and host.tenant_slug:
        tenant = tenant_by_slug(host.tenant_slug)
        if tenant is None:
            raise OtpInvalid()
        if tenant.status != Tenant.Status.ACTIVE:
            raise TenantUnavailable()  # the same neutral answer the pre-login page shows
        return tenant
    if host.kind == HostKind.GENERIC:
        return None
    raise OtpInvalid()


def _has_account(phone: str, tenant: Tenant | None) -> bool:
    if tenant is not None:
        # A shop on hold still gets its code: after verifying, it's told why it can't continue
        # (the request itself looks the same for every number).
        return selectors.retailer_login_for_tenant(
            phone, tenant.pk
        ) is not None or selectors.retailer_on_hold_refused(phone, tenant.pk)
    # Generic domain: also for distributors that are unavailable, so the phone's owner learns
    # (after verifying) that the account is unavailable rather than seeing "wrong code".
    return bool(selectors.retailer_accounts_for_verified_phone(phone, active_only=False))


def request_otp(phone: str, host: HostContext, ip: str | None) -> None:
    """Create an OTP request and send the code if an active account matches (ADR-015)."""
    from apps.accounts.tasks import send_login_otp_sms

    ratelimit.hit(
        "otp:phone", phone, get_platform_setting("platform.otp_rate_per_phone_per_10_minutes"), 600
    )
    ratelimit.hit("otp:ip", ip, get_platform_setting("platform.otp_rate_per_ip_per_hour"), 3600)
    tenant = _scope(host)
    code = _new_code()
    with transaction.atomic():
        row = OTPRequest(
            tenant=tenant,
            phone=phone,
            code_hash=_hash_code(phone, code),
            expires_at=timezone.now() + timedelta(seconds=settings.OTP_TTL_SECONDS),
            ip=ip,
        )
        with _in_scope(tenant):
            row.save(force_insert=True)
        if _has_account(phone, tenant):
            sender = tenant.name if tenant is not None else ""
            transaction.on_commit(lambda: send_login_otp_sms.delay(phone, code, sender))


def _in_scope(tenant: Tenant | None) -> AbstractContextManager[None]:
    return tenant_context(tenant.pk) if tenant is not None else nullcontext()


def _check_code(phone: str, code: str, tenant: Tenant | None) -> None:
    """Consume the latest open code if it matches; count a wrong attempt (committed) if not."""
    limit = get_platform_setting("platform.otp_max_verify_attempts")
    with transaction.atomic(), _in_scope(tenant):
        row = (
            OTPRequest.objects.select_for_update()
            .filter(
                phone=phone, tenant=tenant, consumed_at__isnull=True, expires_at__gt=timezone.now()
            )
            .order_by("-created_at")
            .first()
        )
        ok = False
        if row is not None and row.attempts < limit:
            if secrets.compare_digest(row.code_hash, _hash_code(phone, (code or "").strip())):
                row.consumed_at = timezone.now()
                row.save(update_fields=["consumed_at"])
                ok = True
            else:
                row.attempts += 1
                row.save(update_fields=["attempts"])
    if not ok:
        raise OtpInvalid()


def verify_otp(phone: str, code: str, host: HostContext, ip: str | None) -> LoginOutcome:
    """Verify the code, then sign in (subdomain) or offer the distributor choice (generic)."""
    ratelimit.hit(
        "otp-verify:ip", ip, get_platform_setting("platform.login_rate_per_ip_per_minute"), 60
    )
    tenant = _scope(host)
    _check_code(phone, code, tenant)
    with transaction.atomic():
        if tenant is not None:
            user = selectors.retailer_login_for_tenant(phone, tenant.pk)
            if user is None:
                refuse_if_on_hold(phone, tenant.pk)  # the code was right: say why (ADR-036)
                raise OtpInvalid()  # indistinguishable from a wrong code
            return _authenticated(user, tenant.pk)
        accounts = selectors.retailer_accounts_for_verified_phone(phone)
        if not accounts:
            if selectors.retailer_accounts_for_verified_phone(phone, active_only=False):
                raise TenantUnavailable()
            raise OtpInvalid()
        if len(accounts) == 1:
            only = accounts[0]
            return LoginOutcome(
                status=LoginStatus.HANDOFF,
                user=only.user,
                handoff=create_handoff(only.user, only.tenant),
            )
        raw = _new_secret()
        LoginChallenge.objects.create(
            kind=LoginChallenge.Kind.RETAILER_ACCOUNT_CHOICE,
            token_hash=token_hash(raw),
            phone=phone,
            candidates=[str(a.user.pk) for a in accounts],
            expires_at=timezone.now() + timedelta(seconds=settings.AUTH_CHALLENGE_TTL_SECONDS),
        )
        return LoginOutcome(
            status=LoginStatus.CHOOSE_ACCOUNT,
            user=accounts[0].user,
            choice_token=raw,
            accounts=accounts,
        )


@transaction.atomic
def choose_account(choice_token: str, choice_id: UUID) -> Handoff:
    """The verified phone owner picked a distributor: hand the session to its subdomain."""
    challenge = _consume_challenge(choice_token, LoginChallenge.Kind.RETAILER_ACCOUNT_CHOICE)
    if str(choice_id) not in challenge.candidates:
        raise TokenInvalid()
    account = next(
        (
            a
            for a in selectors.retailer_accounts_for_verified_phone(challenge.phone)
            if a.user.pk == choice_id
        ),
        None,
    )
    if account is None:
        raise TokenInvalid()
    return create_handoff(account.user, account.tenant)


def is_active_retailer_login(user: User, tenant_id: UUID) -> bool:
    return (
        user.tenant_id == tenant_id
        and selectors.retailer_login_for_tenant(user.phone or "", tenant_id) is not None
    )
