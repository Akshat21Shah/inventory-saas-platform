"""The distributor's own settings (spec 5.3): business details, bank details, branding and brand
assets, and the tenant-toggleable feature flags. Every change is audited in the tenant's log."""

import uuid
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

from apps.accounts.models import User
from apps.audit import services as audit
from apps.platform import tenant_services
from apps.platform.models import FeatureFlag, Tenant, TenantBranding, TenantProfile
from apps.platform.selectors import invalidate_public_branding
from apps.platform.validators import validate_hex_color, validate_ifsc, validate_upi_id
from common.crypto import mask
from common.errors import InvalidFields, NotFound
from common.storage import get_storage
from common.tenancy import require_tenant_id
from common.uploads import validate_image

PROFILE_FIELDS = ("invoice_terms", "invoice_footer", "signatory_name")
BANK_FIELDS = (
    "bank_account_name",
    "bank_account_number",
    "bank_ifsc",
    "bank_name",
    "bank_branch",
    "upi_id",
)
BRAND_ASSETS = ("logo", "favicon", "app_icon")
ASSET_KINDS = (*BRAND_ASSETS, "signatory")


def _profile() -> TenantProfile:
    profile: TenantProfile = TenantProfile.objects.select_for_update().get_or_create()[0]
    return profile


def _branding() -> TenantBranding:
    branding: TenantBranding = TenantBranding.objects.select_for_update().get_or_create()[0]
    return branding


@transaction.atomic
def update_business(changes: dict[str, Any], *, by: User) -> Tenant:
    """Legal and contact details (Tenant) and document texts (profile). The web address (slug) is
    changed only by super admins (ADR-030)."""
    tenant_changes = {
        k: v for k, v in changes.items() if k in tenant_services.TENANT_BUSINESS_FIELDS
    }
    tenant = tenant_services.update_tenant(require_tenant_id(), tenant_changes, by=by)
    profile_changes = {k: v for k, v in changes.items() if k in PROFILE_FIELDS}
    if profile_changes:
        profile = _profile()
        before = {f: getattr(profile, f) for f in PROFILE_FIELDS}
        for field, value in profile_changes.items():
            setattr(profile, field, value.strip())
        diff = audit.diff(before, {f: getattr(profile, f) for f in PROFILE_FIELDS})
        if diff:
            profile.save()
            audit.record("settings.business_profile_changed", target=profile, changes=diff)
    return tenant


@transaction.atomic
def update_bank_details(changes: dict[str, Any], *, by: User) -> TenantProfile:
    """Bank details printed on invoices; the account number is encrypted and masked in the log."""
    profile = _profile()
    before = {f: getattr(profile, f) for f in BANK_FIELDS}
    for field, value in changes.items():
        if field in BANK_FIELDS:
            setattr(
                profile,
                field,
                (value or "").strip().upper() if field == "bank_ifsc" else (value or "").strip(),
            )
    errors: dict[str, list[str]] = {}
    for field, validator in (("bank_ifsc", validate_ifsc), ("upi_id", validate_upi_id)):
        value = getattr(profile, field)
        if value:
            try:
                validator(value)
            except DjangoValidationError as exc:
                errors[field] = list(exc.messages)
    number = profile.bank_account_number
    if number and (not number.isdigit() or not 6 <= len(number) <= 20):
        errors["bank_account_number"] = ["Enter the account number (6 to 20 digits)."]
    if errors:
        raise InvalidFields(errors)
    diff = audit.diff(
        before, {f: getattr(profile, f) for f in BANK_FIELDS}, masked={"bank_account_number"}
    )
    if diff:
        profile.save()
        audit.record("settings.bank_details_changed", target=profile, changes=diff)
    return profile


def bank_details(profile: TenantProfile) -> dict[str, Any]:
    """For display: the account number is never returned in full."""
    return {
        "bank_account_name": profile.bank_account_name,
        "bank_account_number_masked": mask(profile.bank_account_number),
        "bank_ifsc": profile.bank_ifsc,
        "bank_name": profile.bank_name,
        "bank_branch": profile.bank_branch,
        "upi_id": profile.upi_id,
    }


@transaction.atomic
def update_branding(changes: dict[str, Any], *, by: User) -> TenantBranding:
    branding = _branding()
    fields = ("display_name", "primary_color")
    before = {f: getattr(branding, f) for f in fields}
    if "display_name" in changes:
        branding.display_name = changes["display_name"].strip()
    if "primary_color" in changes:
        color = changes["primary_color"].strip().lower()
        try:
            validate_hex_color(color)
        except DjangoValidationError as exc:
            raise InvalidFields({"primary_color": list(exc.messages)}) from exc
        branding.primary_color = color
    diff = audit.diff(before, {f: getattr(branding, f) for f in fields})
    if diff:
        branding.updated_by = by
        branding.save()
        audit.record("settings.branding_changed", target=branding, changes=diff)
        _refresh_public_branding()
    return branding


def _refresh_public_branding() -> None:
    """The sign-in page's cached branding must show the change on the next request."""
    tenant_id = require_tenant_id()
    transaction.on_commit(lambda: invalidate_public_branding(tenant_id))


def _asset_key(kind: str, extension: str) -> str:
    return f"tenants/{require_tenant_id()}/branding/{kind}/{uuid.uuid4().hex}.{extension}"


def _delete_later(key: str) -> None:
    """Remove the replaced object after commit (a failed delete only leaves an orphan file)."""
    from apps.platform.tasks import delete_stored_object

    if key:
        transaction.on_commit(lambda: delete_stored_object.delay(key))


@transaction.atomic
def upload_asset(kind: str, upload: "UploadedFile[bytes]", *, by: User) -> str:
    """Store a validated image (ADR-027) and point the branding/profile at it."""
    if kind not in ASSET_KINDS:
        raise NotFound()
    image = validate_image(upload)
    key = _asset_key(kind, image.extension)
    # Stored before the DB change; if the transaction then fails, the object is an orphan under
    # the tenant's prefix (harmless, never referenced).
    get_storage().put(key, image.data, image.content_type)
    holder: TenantBranding | TenantProfile
    if kind == "signatory":
        holder, field = _profile(), "signatory_image"
    else:
        holder, field = _branding(), kind
    old = getattr(holder, field)
    setattr(holder, field, key)
    holder.save()
    audit.record(
        "settings.asset_uploaded",
        target=holder,
        metadata={"kind": kind, "content_type": image.content_type, "bytes": len(image.data)},
    )
    _delete_later(old)
    _refresh_public_branding()
    return key


@transaction.atomic
def remove_asset(kind: str, *, by: User) -> None:
    if kind not in ASSET_KINDS:
        raise NotFound()
    holder: TenantBranding | TenantProfile
    if kind == "signatory":
        holder, field = _profile(), "signatory_image"
    else:
        holder, field = _branding(), kind
    old = getattr(holder, field)
    if not old:
        return
    setattr(holder, field, "")
    holder.save()
    audit.record("settings.asset_removed", target=holder, metadata={"kind": kind})
    _delete_later(old)
    _refresh_public_branding()


@transaction.atomic
def toggle_feature(code: str, enabled: bool, *, by: User) -> bool:
    """Distributors may switch only the flags the platform marked tenant-toggleable."""
    flag = FeatureFlag.objects.filter(code=code).first()
    if flag is None:
        raise NotFound()
    if not flag.tenant_toggleable:
        raise InvalidFields({"enabled": ["This module is managed by the platform team."]})
    return tenant_services.set_tenant_feature(require_tenant_id(), code, enabled, by=by)
