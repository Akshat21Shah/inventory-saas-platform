"""Tenant lifecycle for super admins: onboarding, edits, suspension, flags, plans (spec 5.1).

Writes to a tenant's own rows run inside that tenant's RLS context on the runtime connection;
every change is recorded in the tenant's audit log, so its owners can see what the platform did.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts import staff_services
from apps.accounts.models import Invitation, Membership, User
from apps.accounts.permissions import OWNER_ROLE
from apps.audit import services as audit
from apps.catalog.defaults import ensure_default_units
from apps.catalog.models import Unit
from apps.platform.models import (
    DEFAULT_BRAND_COLOR,
    FeatureFlag,
    Plan,
    State,
    Subscription,
    Tenant,
    TenantBranding,
    TenantFeature,
    TenantProfile,
)
from apps.platform.selectors import invalidate_tenant_features, invalidate_tenant_info
from apps.platform.validators import gstin_format_error, normalize_gstin
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields, NotFound
from common.tenancy import tenant_context

# Business fields a super admin (onboarding/edit) and the distributor (settings) may change.
TENANT_BUSINESS_FIELDS = (
    "name",
    "legal_name",
    "gstin",
    "pan",
    "state_id",
    "address_line1",
    "address_line2",
    "city",
    "pincode",
    "email",
    "phone",
)


class SlugChangeNotConfirmed(DomainError):
    status_code = 400
    code = ErrorCode.SLUG_CHANGE_NOT_CONFIRMED
    default_message = "Confirm the web address change to continue."


@dataclass(frozen=True)
class OnboardingInput:
    name: str
    legal_name: str
    gstin: str
    state_id: str
    address_line1: str
    address_line2: str
    city: str
    pincode: str
    email: str
    phone: str
    slug: str
    owner_email: str
    owner_name: str = ""
    plan_code: str | None = None
    primary_color: str | None = None


def _validate_tenant(tenant: Tenant, exclude: list[str] | None = None) -> None:
    """Model validation (GSTIN checksum, PAN, pincode, slug rules...) as field errors."""
    try:
        tenant.full_clean(exclude=exclude, validate_unique=True, validate_constraints=True)
    except DjangoValidationError as exc:
        fields = {k: [str(m) for m in v] for k, v in exc.message_dict.items()}
        for model_name in ("state", "state_id"):  # the API calls it state_code
            if model_name in fields:
                fields["state_code"] = fields.pop(model_name)
        raise InvalidFields(fields) from exc


def _check_gst_identity(tenant: Tenant) -> None:
    """GSTIN rules with plain, specific messages (spec 5.1). The PAN is never an input: it is
    characters 3 to 12 of the GSTIN (a check constraint enforces this too)."""
    errors: dict[str, list[str]] = {}
    problem = gstin_format_error(tenant.gstin)
    if problem is None:
        state = State.objects.filter(code=tenant.gstin[:2]).first()
        if state is None:
            problem = f"The first 2 digits ({tenant.gstin[:2]}) are not a GST state code."
        elif not state.is_active:
            problem = (
                f"State code {state.code} ({state.name}) is no longer used for new registrations."
            )
    if problem is None and (
        Tenant.objects.filter(gstin=tenant.gstin).exclude(pk=tenant.pk).exists()
    ):
        problem = "Another business is already registered with this GSTIN."
    if problem is not None:
        errors["gstin"] = [problem]
    elif tenant.state_id != tenant.gstin[:2]:
        errors["state_code"] = [
            f"The state must match the first 2 digits of the GSTIN ({tenant.gstin[:2]})."
        ]
    if errors:
        raise InvalidFields(errors)


@transaction.atomic
def onboard_tenant(data: OnboardingInput, *, by: User) -> Tenant:
    """Create a distributor in one transaction (spec 5.1 onboarding wizard, PLAN 1.9)."""
    gstin = normalize_gstin(data.gstin)
    plan = (
        Plan.objects.filter(code=data.plan_code, is_active=True).first()
        if data.plan_code
        else Plan.objects.get(is_default=True)
    )
    if plan is None:
        raise InvalidFields({"plan_code": ["Choose an active plan."]})
    tenant = Tenant(
        name=data.name.strip(),
        legal_name=data.legal_name.strip(),
        gstin=gstin,
        pan=gstin[2:12],
        state_id=data.state_id,
        address_line1=data.address_line1.strip(),
        address_line2=data.address_line2.strip(),
        city=data.city.strip(),
        pincode=data.pincode.strip(),
        email=data.email.strip().lower(),
        phone=data.phone.strip(),
        slug=data.slug.strip().lower(),
        status=Tenant.Status.ONBOARDING,
    )
    _check_gst_identity(tenant)
    _validate_tenant(tenant)
    tenant.save(force_insert=True)
    with tenant_context(tenant.pk):
        TenantProfile.objects.create(created_by=by)
        TenantBranding.objects.create(
            display_name=tenant.name,
            primary_color=(data.primary_color or DEFAULT_BRAND_COLOR).lower(),
            updated_by=by,
            created_by=by,
        )
        Subscription.objects.create(plan=plan, starts_at=timezone.now(), created_by=by)
        ensure_default_units(Unit)
        audit.record(
            "tenant.created",
            target=tenant,
            metadata={"slug": tenant.slug, "plan": plan.code, "owner_email": data.owner_email},
        )
        staff_services.invite_staff(email=data.owner_email, role_code=OWNER_ROLE, invited_by=by)
    return tenant


def _tenant(tenant_id: UUID, *, lock: bool = False) -> Tenant:
    qs = Tenant.objects.select_for_update() if lock else Tenant.objects
    tenant: Tenant | None = qs.filter(pk=tenant_id).first()
    if tenant is None:
        raise NotFound()
    return tenant


@transaction.atomic
def update_tenant(
    tenant_id: UUID, changes: dict[str, Any], *, by: User, confirm_slug_change: bool = False
) -> Tenant:
    """Edit business details (and, for super admins, the slug after confirmation; ADR-030)."""
    tenant = _tenant(tenant_id, lock=True)
    allowed = {*TENANT_BUSINESS_FIELDS, "slug"}
    before = {f: getattr(tenant, f) for f in allowed}
    for field, value in changes.items():
        if field not in allowed or field == "pan":  # the PAN always follows the GSTIN
            continue
        if field == "gstin":
            value = normalize_gstin(value)
            tenant.pan = value[2:12]
        elif field in ("email", "slug"):
            value = value.strip().lower()
        elif isinstance(value, str):
            value = value.strip()
        setattr(tenant, field, value)
    if tenant.slug != before["slug"] and not confirm_slug_change:
        raise SlugChangeNotConfirmed()
    _check_gst_identity(tenant)
    _validate_tenant(tenant)
    diff = audit.diff(before, {f: getattr(tenant, f) for f in allowed})
    if not diff:
        return tenant
    tenant.save()
    audit.record("tenant.updated", target=tenant, tenant_id=tenant.pk, changes=diff)
    if "slug" in diff:
        audit.record(
            "tenant.slug_changed",
            target=tenant,
            tenant_id=tenant.pk,
            changes={"slug": diff["slug"]},
        )
    old_slug = before["slug"]
    transaction.on_commit(lambda: invalidate_tenant_info(tenant.pk, old_slug))
    return tenant


@transaction.atomic
def suspend_tenant(tenant_id: UUID, *, reason: str, by: User) -> Tenant:
    """ADR-018: every login of this tenant stops at once; all data is kept."""
    tenant = _tenant(tenant_id, lock=True)
    if not reason.strip():
        raise InvalidFields({"reason": ["Enter the reason for suspending this business."]})
    if tenant.status == Tenant.Status.SUSPENDED:
        return tenant
    old = tenant.status
    tenant.status, tenant.suspended_reason, tenant.suspended_at = (
        Tenant.Status.SUSPENDED,
        reason.strip(),
        timezone.now(),
    )
    tenant.save(update_fields=["status", "suspended_reason", "suspended_at", "updated_at"])
    audit.record(
        "tenant.suspended",
        target=tenant,
        tenant_id=tenant.pk,
        changes={"status": [old, Tenant.Status.SUSPENDED]},
        metadata={"reason": tenant.suspended_reason},
    )
    transaction.on_commit(lambda: invalidate_tenant_info(tenant.pk))
    return tenant


@transaction.atomic
def reactivate_tenant(tenant_id: UUID, *, by: User) -> Tenant:
    """Back to ACTIVE, or to ONBOARDING if no owner has joined yet."""
    tenant = _tenant(tenant_id, lock=True)
    if tenant.status != Tenant.Status.SUSPENDED:
        return tenant
    with tenant_context(tenant.pk):
        has_owner = Membership.objects.filter(
            is_active=True, role__code=OWNER_ROLE, role__tenant__isnull=True
        ).exists()
    new = Tenant.Status.ACTIVE if has_owner else Tenant.Status.ONBOARDING
    tenant.status, tenant.suspended_reason, tenant.suspended_at = new, "", None
    tenant.save(update_fields=["status", "suspended_reason", "suspended_at", "updated_at"])
    audit.record(
        "tenant.reactivated",
        target=tenant,
        tenant_id=tenant.pk,
        changes={"status": [Tenant.Status.SUSPENDED, new]},
    )
    transaction.on_commit(lambda: invalidate_tenant_info(tenant.pk))
    return tenant


@transaction.atomic
def set_tenant_feature(tenant_id: UUID, code: str, enabled: bool, *, by: User) -> bool:
    """Turn a module on or off for one tenant. Only overrides of the default are stored."""
    tenant = _tenant(tenant_id)
    flag = FeatureFlag.objects.filter(code=code).first()
    if flag is None:
        raise NotFound()
    with tenant_context(tenant.pk):
        current = TenantFeature.objects.filter(flag=flag).first()
        old = current.enabled if current is not None else flag.default_enabled
        if old == enabled:
            return enabled
        if enabled == flag.default_enabled:
            TenantFeature.objects.filter(flag=flag).delete()
        else:
            TenantFeature.objects.update_or_create(
                flag=flag, defaults={"enabled": enabled, "updated_by": by}
            )
        audit.record(
            "feature.changed",
            target_type="feature",
            target_id=code,
            target_repr=flag.name,
            changes={"enabled": [old, enabled]},
        )
    transaction.on_commit(lambda: invalidate_tenant_features(tenant.pk))
    return enabled


@transaction.atomic
def change_plan(tenant_id: UUID, plan_code: str, *, by: User) -> Subscription:
    tenant = _tenant(tenant_id)
    plan = Plan.objects.filter(code=plan_code, is_active=True).first()
    if plan is None:
        raise InvalidFields({"plan_code": ["Choose an active plan."]})
    with tenant_context(tenant.pk):
        current: Subscription | None = (
            Subscription.objects.select_for_update().filter(is_current=True).first()
        )
        if current is not None and current.plan_id == plan.pk:
            return current
        now = timezone.now()
        if current is not None:
            current.is_current, current.ends_at = False, now
            current.save(update_fields=["is_current", "ends_at", "updated_at"])
        subscription: Subscription = Subscription.objects.create(
            plan=plan, starts_at=now, created_by=by
        )
        audit.record(
            "subscription.plan_changed",
            target=subscription,
            changes={"plan": [current.plan.code if current else None, plan.code]},
        )
    return subscription


@transaction.atomic
def resend_owner_invitation(tenant_id: UUID, *, by: User) -> Invitation:
    """ADR-030: while ONBOARDING, send the owner a fresh link (the previous one stops working)."""
    tenant = _tenant(tenant_id)
    if tenant.status != Tenant.Status.ONBOARDING:
        raise InvalidFields({"status": ["The owner has already joined this business."]})
    with tenant_context(tenant.pk):
        invitation = (
            Invitation.objects.filter(role__code=OWNER_ROLE, role__tenant__isnull=True)
            .exclude(status__in=[Invitation.Status.ACCEPTED, Invitation.Status.REVOKED])
            .order_by("-created_at")
            .first()
        )
        if invitation is None:
            raise NotFound()
        return staff_services.resend_invitation(invitation.pk, by=by)


def slug_available(slug: str) -> bool:
    try:
        Tenant(slug=slug).clean_fields(
            exclude=[f.name for f in Tenant._meta.fields if f.name != "slug"]
        )
    except DjangoValidationError:
        return False
    return not Tenant.objects.filter(slug=slug).exists()
