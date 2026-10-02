"""Support impersonation (spec 5.1, ADR-029).

A super admin starts a session with a reason; it opens READ-ONLY on the tenant's subdomain via a
handoff code. The access token cannot be refreshed and ends with the session. Switching to ACT
needs a second reason. Credential, staff/role and bank-detail changes stay blocked in every mode
(endpoints marked ``impersonation_blocked``). Start, ACT, end and expiry are written to the
tenant's own audit log, so its owners see every support session.
"""

from datetime import datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.utils import datetime_from_epoch

from apps.accounts import selectors
from apps.accounts.models import HandoffCode, ImpersonationSession, User
from apps.accounts.services import Handoff, LoginOutcome, LoginStatus, create_handoff
from apps.accounts.tokens import USER_TYPE_CLAIM, IssuedTokens
from apps.audit import services as audit
from apps.platform.models import Tenant
from apps.platform.selectors import get_platform_setting
from common.authentication import (
    IMPERSONATION_MODE_CLAIM,
    IMPERSONATION_SESSION_CLAIM,
    IMPERSONATOR_CLAIM,
    TENANT_CLAIM,
)
from common.context import Actor
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields, NotFound
from common.platform_db import platform_db
from common.tenancy import tenant_context


class ImpersonationReadOnly(DomainError):
    status_code = 403
    code = ErrorCode.IMPERSONATION_READ_ONLY
    default_message = gettext_lazy("This support session is view-only.")


class ImpersonationBlocked(DomainError):
    status_code = 403
    code = ErrorCode.IMPERSONATION_BLOCKED
    default_message = gettext_lazy("This can't be done in a support session.")


def _admin_actor(session: ImpersonationSession) -> Actor:
    return Actor(user_id=session.impersonator_id, actor_type=User.UserType.PLATFORM)


def _target_is_valid(target: User, tenant: Tenant) -> bool:
    if not target.is_active:
        return False
    if target.user_type == User.UserType.STAFF:
        return selectors.active_membership(target, tenant.pk) is not None
    if target.user_type == User.UserType.RETAILER:
        return (
            target.tenant_id == tenant.pk
            and selectors.retailer_login_for_tenant(target.phone or "", tenant.pk) is not None
        )
    return False  # super admins are never impersonated


@transaction.atomic
def start_impersonation(
    *,
    admin: User,
    tenant_id: UUID,
    user_id: UUID,
    reason: str,
    ip: str | None,
    user_agent: str,
) -> tuple[ImpersonationSession, Handoff]:
    if not reason.strip():
        raise InvalidFields({"reason": [_("Enter why you need to act as this user.")]})
    tenant = Tenant.objects.filter(pk=tenant_id).first()
    target = User.objects.filter(pk=user_id).first()
    if tenant is None or target is None:
        raise NotFound()
    if target.user_type == User.UserType.PLATFORM or not _target_is_valid(target, tenant):
        raise InvalidFields({"user_id": [_("This user can't be impersonated.")]})
    minutes = get_platform_setting("platform.impersonation_session_minutes")
    with tenant_context(tenant.pk):
        session = ImpersonationSession.objects.create(
            impersonator=admin,
            target_user=target,
            reason=reason.strip(),
            expires_at=timezone.now() + timedelta(minutes=minutes),
            ip=ip,
            user_agent=user_agent[:500],
        )
        audit.record(
            "impersonation.started",
            target=session,
            target_repr=target.email or target.phone or str(target.pk),
            actor=_admin_actor(session),
            metadata={
                "reason": session.reason,
                "minutes": minutes,
                "target_user_id": str(target.pk),
            },
        )
    handoff = create_handoff(
        target, tenant, session_expires_at=session.expires_at, impersonation_session_id=session.pk
    )
    return session, handoff


def _access_token(session: ImpersonationSession) -> tuple[str, datetime]:
    """A non-refreshable access token that expires with the session."""
    target = session.target_user
    token = AccessToken.for_user(target)
    token[TENANT_CLAIM] = str(session.tenant_id)
    token[USER_TYPE_CLAIM] = target.user_type
    token[IMPERSONATION_SESSION_CLAIM] = str(session.pk)
    token[IMPERSONATOR_CLAIM] = str(session.impersonator_id)
    token[IMPERSONATION_MODE_CLAIM] = session.mode
    now = timezone.now()
    token.set_exp(from_time=now, lifetime=max(session.expires_at - now, timedelta(seconds=1)))
    return str(token), datetime_from_epoch(token["exp"])


def complete_handoff(handoff: HandoffCode) -> LoginOutcome:
    """Handoff exchange for an impersonation: an access token only (no refresh cookie)."""
    with tenant_context(handoff.tenant_id):
        session = (
            ImpersonationSession.objects.select_related("target_user")
            .filter(pk=handoff.impersonation_session_id)
            .first()
        )
        if session is None or not session.is_open():
            from apps.accounts.services import TokenInvalid

            raise TokenInvalid()
        access, expires = _access_token(session)
    tokens = IssuedTokens(
        access=access,
        access_expires_at=expires,
        refresh="",
        refresh_expires_at=expires,
        session_expires_at=expires,
    )
    return LoginOutcome(status=LoginStatus.AUTHENTICATED, user=session.target_user, tokens=tokens)


def open_session(session_id: UUID, tenant_id: UUID) -> ImpersonationSession | None:
    """The session if it is still open (checked on every impersonated request)."""
    with transaction.atomic(), tenant_context(tenant_id):
        session: ImpersonationSession | None = ImpersonationSession.objects.filter(
            pk=session_id, ended_at__isnull=True, expires_at__gt=timezone.now()
        ).first()
    return session


@transaction.atomic
def enable_act_mode(session: ImpersonationSession, reason: str) -> tuple[str, datetime]:
    if not reason.strip():
        raise InvalidFields({"reason": [_("Enter why you need to make changes.")]})
    with tenant_context(session.tenant_id):
        locked = (
            ImpersonationSession.objects.select_for_update()
            .select_related("target_user")
            .get(pk=session.pk)
        )
        if locked.mode != ImpersonationSession.Mode.ACT:
            locked.mode = ImpersonationSession.Mode.ACT
            locked.act_reason = reason.strip()
            locked.act_started_at = timezone.now()
            locked.save(update_fields=["mode", "act_reason", "act_started_at", "updated_at"])
            audit.record(
                "impersonation.act_enabled",
                target=locked,
                actor=_admin_actor(locked),
                metadata={"reason": locked.act_reason},
            )
        return _access_token(locked)


@transaction.atomic
def end_impersonation(
    session: ImpersonationSession, end_reason: str = ImpersonationSession.EndReason.ENDED
) -> None:
    with tenant_context(session.tenant_id):
        updated = ImpersonationSession.objects.filter(pk=session.pk, ended_at__isnull=True).update(
            ended_at=timezone.now(), end_reason=end_reason
        )
        if updated:
            audit.record(
                f"impersonation.{end_reason.lower()}",
                target=session,
                actor=_admin_actor(session),
            )


def expire_sessions() -> int:
    """Close sessions past their end time and record the expiry (beat task)."""
    alias = platform_db("accounts.expire_impersonation_sessions")
    due = list(
        ImpersonationSession.objects.unscoped()
        .using(alias)
        .filter(ended_at__isnull=True, expires_at__lte=timezone.now())
        .values_list("pk", "tenant_id")
    )
    for session_id, tenant_id in due:
        with transaction.atomic(), tenant_context(tenant_id):
            session = ImpersonationSession.objects.filter(pk=session_id).first()
            if session is not None:
                end_impersonation(session, ImpersonationSession.EndReason.EXPIRED)
    return len(due)


def history(tenant_id: UUID | None = None) -> QuerySet[ImpersonationSession]:
    """All sessions, newest first (super admin view)."""
    qs = (
        ImpersonationSession.objects.unscoped()
        .using(platform_db("accounts.impersonation_history"))
        .select_related("impersonator", "target_user", "tenant")
        .order_by("-created_at")
    )
    return qs.filter(tenant_id=tenant_id) if tenant_id else qs
