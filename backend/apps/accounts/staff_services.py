"""Staff management and invitations (spec 5.2 "staff invitation by email", PLAN §3.4, ADR-030).

All functions act in the active tenant (RLS + tenant-scoped managers) except the invitation
preview/accept pair, which resolve the tenant from the subdomain the link points to.
"""

import secrets
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Invitation, Membership, Role, User
from apps.accounts.permissions import OWNER_ROLE
from apps.accounts.services import (
    LoginOutcome,
    TenantUnavailable,
    TokenInvalid,
    _continue_login,
    _tokens_target,
    token_hash,
)
from apps.audit import services as audit
from apps.platform.models import Tenant
from apps.platform.selectors import (
    PlanResource,
    invalidate_tenant_info,
    plan_limit_allows,
    tenant_by_slug,
)
from common.context import Actor
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields, NotFound
from common.hosts import HostContext, HostKind
from common.tenancy import require_tenant_id, tenant_context


class PlanLimitReached(DomainError):
    status_code = 403
    code = ErrorCode.PLAN_LIMIT_REACHED
    default_message = "Your plan's limit has been reached."


class LastOwner(DomainError):
    status_code = 400
    code = ErrorCode.LAST_OWNER
    default_message = "Every business needs at least one active owner."


class AlreadyAMember(DomainError):
    status_code = 409
    code = ErrorCode.ALREADY_A_MEMBER
    default_message = "This person is already on your team."


def assignable_role(role_code: str) -> Role:
    """A tenant role: a system role other than platform roles, or this tenant's custom role."""
    tenant_id = require_tenant_id()
    candidates = Role.objects.filter(code=role_code, is_platform=False)
    role: Role | None = (
        candidates.filter(tenant_id=tenant_id).first()
        or candidates.filter(tenant__isnull=True).first()
    )
    if role is None:
        raise InvalidFields({"role_code": ["Choose one of the listed roles."]})
    return role


def _staff_count(tenant_id: UUID) -> int:
    active = Membership.objects.filter(is_active=True).count()
    pending = Invitation.objects.filter(
        status=Invitation.Status.PENDING, expires_at__gt=timezone.now()
    ).count()
    return active + pending


def _require_seat(tenant_id: UUID) -> None:
    if not plan_limit_allows(PlanResource.STAFF, _staff_count(tenant_id), tenant_id):
        raise PlanLimitReached()


def _send(invitation: Invitation, raw: str) -> None:
    from apps.accounts.tasks import send_invitation_email

    tenant_id = invitation.tenant_id
    invitation_id = str(invitation.pk)
    transaction.on_commit(
        lambda: send_invitation_email.delay(
            invitation_id=invitation_id, raw_token=raw, tenant_id=str(tenant_id)
        )
    )


def _fresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, token_hash(raw)


def _expiry() -> Any:
    return timezone.now() + timedelta(days=settings.INVITATION_TTL_DAYS)


@transaction.atomic
def invite_staff(*, email: str, role_code: str, invited_by: User | None) -> Invitation:
    tenant_id = require_tenant_id()
    email = email.strip().lower()
    role = assignable_role(role_code)
    existing = User.objects.filter(email=email).first()
    if existing is not None and existing.user_type != User.UserType.STAFF:
        raise InvalidFields({"email": ["This email can't be invited."]})
    if existing is not None and Membership.objects.filter(user=existing, is_active=True).exists():
        raise AlreadyAMember()
    if Invitation.objects.filter(
        email=email, status=Invitation.Status.PENDING, expires_at__gt=timezone.now()
    ).exists():
        raise InvalidFields(
            {"email": ["An invitation is already waiting for this email. Resend it instead."]}
        )
    # A stale pending row (expired) would block the partial unique index: mark it expired.
    Invitation.objects.filter(email=email, status=Invitation.Status.PENDING).update(
        status=Invitation.Status.EXPIRED
    )
    _require_seat(tenant_id)
    raw, digest = _fresh_token()
    invitation: Invitation = Invitation.objects.create(
        email=email, role=role, token_hash=digest, expires_at=_expiry(), invited_by=invited_by
    )
    audit.record(
        "staff.invited",
        target=invitation,
        target_repr=email,
        metadata={"email": email, "role": role.code},
    )
    _send(invitation, raw)
    return invitation


def _pending(invitation_id: UUID) -> Invitation:
    invitation: Invitation | None = (
        Invitation.objects.select_for_update().filter(pk=invitation_id).first()
    )
    if invitation is None:
        raise NotFound()
    if invitation.status not in (Invitation.Status.PENDING, Invitation.Status.EXPIRED):
        raise InvalidFields({"status": ["This invitation can no longer be changed."]})
    return invitation


@transaction.atomic
def resend_invitation(invitation_id: UUID, *, by: User | None) -> Invitation:
    """New link (the old one stops working) and a new expiry."""
    invitation = _pending(invitation_id)
    if invitation.status == Invitation.Status.EXPIRED:
        _require_seat(require_tenant_id())
    raw, digest = _fresh_token()
    invitation.token_hash, invitation.expires_at = digest, _expiry()
    invitation.status = Invitation.Status.PENDING
    invitation.save(update_fields=["token_hash", "expires_at", "status", "updated_at"])
    audit.record("staff.invitation_resent", target=invitation, target_repr=invitation.email)
    _send(invitation, raw)
    return invitation


@transaction.atomic
def revoke_invitation(invitation_id: UUID, *, by: User | None) -> Invitation:
    invitation = _pending(invitation_id)
    invitation.status = Invitation.Status.REVOKED
    invitation.save(update_fields=["status", "updated_at"])
    audit.record("staff.invitation_revoked", target=invitation, target_repr=invitation.email)
    return invitation


# --- Accepting (public, on the tenant's subdomain) --------------------------------------------


def _tenant_for_link(host: HostContext) -> Tenant:
    tenant = tenant_by_slug(host.tenant_slug or "") if host.kind == HostKind.TENANT else None
    if tenant is None:
        raise TokenInvalid()
    if tenant.status not in (Tenant.Status.ACTIVE, Tenant.Status.ONBOARDING):
        # Onboarding stays open: accepting the owner's invitation is what activates the tenant.
        raise TenantUnavailable()
    return tenant


def _open_invitation(raw: str, *, lock: bool = False) -> Invitation:
    qs = Invitation.objects.select_related("role", "invited_by")
    if lock:
        qs = qs.select_for_update(of=("self",))
    invitation: Invitation | None = qs.filter(
        token_hash=token_hash(raw or ""),
        status=Invitation.Status.PENDING,
        expires_at__gt=timezone.now(),
    ).first()
    if invitation is None:
        raise TokenInvalid()
    return invitation


def preview_invitation(raw: str, host: HostContext) -> dict[str, Any]:
    """What the invite page shows: who invites whom, as what, and whether to set a password."""
    tenant = _tenant_for_link(host)
    with transaction.atomic(), tenant_context(tenant.pk):
        invitation = _open_invitation(raw)
        existing = User.objects.filter(email=invitation.email, user_type=User.UserType.STAFF)
        return {
            "tenant_name": tenant.name,
            "email": invitation.email,
            "role": {"code": invitation.role.code, "name": invitation.role.name},
            "invited_by": invitation.invited_by.full_name if invitation.invited_by else "",
            "existing_account": existing.exists(),
            "expires_at": invitation.expires_at,
        }


def _joining_user(invitation: Invitation, full_name: str, password: str) -> User:
    user = User.objects.filter(email=invitation.email).first()
    if user is None:
        candidate = User(email=invitation.email, full_name=full_name.strip(), user_type="STAFF")
        try:
            validate_password(password, candidate)
        except DjangoValidationError as exc:
            raise InvalidFields({"password": list(exc.messages)}) from exc
        if not full_name.strip():
            raise InvalidFields({"full_name": ["Enter your name."]})
        return User.objects.create_user(
            invitation.email, password, user_type=User.UserType.STAFF, full_name=full_name.strip()
        )
    if user.user_type != User.UserType.STAFF or not user.is_active:
        raise TokenInvalid()
    if not user.check_password(password):
        raise InvalidFields({"password": ["Enter the password of your existing account."]})
    return user


def accept_invitation(
    raw: str, host: HostContext, *, full_name: str, password: str
) -> LoginOutcome:
    """Join the tenant (new account, or existing staff account confirmed by its password) and
    sign in. The owner accepting an ONBOARDING tenant's invitation activates it (ADR-030)."""
    tenant = _tenant_for_link(host)
    with transaction.atomic(), tenant_context(tenant.pk):
        invitation = _open_invitation(raw, lock=True)
        user = _joining_user(invitation, full_name, password)
        membership = Membership.objects.filter(user=user).first()
        if membership is not None and membership.is_active:
            raise AlreadyAMember()
        if membership is None:
            Membership.objects.create(
                user=user, role=invitation.role, invited_by=invitation.invited_by
            )
        else:
            membership.role, membership.is_active = invitation.role, True
            membership.save(update_fields=["role", "is_active", "updated_at"])
        invitation.status, invitation.accepted_at = Invitation.Status.ACCEPTED, timezone.now()
        invitation.accepted_user = user
        invitation.save(update_fields=["status", "accepted_at", "accepted_user", "updated_at"])
        actor = Actor(user_id=user.pk, actor_type=user.user_type)
        audit.record(
            "staff.invitation_accepted",
            target=invitation,
            target_repr=invitation.email,
            actor=actor,
            metadata={"role": invitation.role.code},
        )
        if tenant.status == Tenant.Status.ONBOARDING and invitation.role.code == OWNER_ROLE:
            Tenant.objects.filter(pk=tenant.pk).update(status=Tenant.Status.ACTIVE)
            audit.record(
                "tenant.activated",
                target=tenant,
                actor=actor,
                changes={"status": [Tenant.Status.ONBOARDING, Tenant.Status.ACTIVE]},
            )
            transaction.on_commit(lambda: invalidate_tenant_info(tenant.pk))
        return _continue_login(user, _tokens_target(host, tenant.pk))


# --- Members ------------------------------------------------------------------------------------


def _active_owner_ids() -> list[UUID]:
    """Lock the active owner memberships (in id order, no deadlocks) and return their ids."""
    return list(
        Membership.objects.select_for_update()
        .filter(is_active=True, role__code=OWNER_ROLE, role__tenant__isnull=True)
        .order_by("pk")
        .values_list("pk", flat=True)
    )


@transaction.atomic
def change_member(
    membership_id: UUID,
    *,
    by: User,
    role_code: str | None = None,
    is_active: bool | None = None,
) -> Membership:
    """Change a member's role and/or deactivate/reactivate them (ADR-030 owner rules)."""
    owners = _active_owner_ids()
    membership: Membership | None = (
        Membership.objects.select_for_update(of=("self",))
        .select_related("role", "user")
        .filter(pk=membership_id)
        .first()
    )
    if membership is None:
        raise NotFound()
    new_role = assignable_role(role_code) if role_code else membership.role
    new_active = membership.is_active if is_active is None else is_active
    was_owner = membership.is_active and membership.role.code == OWNER_ROLE
    stays_owner = new_active and new_role.code == OWNER_ROLE
    if was_owner and not stays_owner and owners == [membership.pk]:
        raise LastOwner()
    if membership.user_id == by.pk and membership.is_active and not new_active:
        raise InvalidFields({"is_active": ["You can't deactivate yourself."]})
    if new_active and not membership.is_active:
        _require_seat(require_tenant_id())

    changes: dict[str, list[Any]] = {}
    if new_role.pk != membership.role_id:
        changes["role"] = [membership.role.code, new_role.code]
    if new_active != membership.is_active:
        changes["is_active"] = [membership.is_active, new_active]
    if not changes:
        return membership
    membership.role, membership.is_active = new_role, new_active
    membership.save(update_fields=["role", "is_active", "updated_at"])
    action = (
        "staff.role_changed"
        if "is_active" not in changes
        else ("staff.reactivated" if new_active else "staff.deactivated")
    )
    audit.record(
        action, target=membership, target_repr=membership.user.email or "", changes=changes
    )
    return membership
