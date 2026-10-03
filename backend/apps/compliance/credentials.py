"""A distributor's GST provider credentials (ADR-049 items 1 and 7): the super admin switches the
module on, the owner (``settings.manage``) enters the credentials and checks them.

- They are for the business's own GSTIN and the platform's chosen provider (``GSP_PROVIDER``).
- Secrets are encrypted at rest and never returned: reads show the last characters only, and a
  blank field on save keeps what is stored.
- Saving or changing them needs a new check. The check signs in with the provider in the
  background (``compliance.verify_credentials``), so no request waits on the provider.
"""

import json
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.models import User
from apps.audit import services as audit
from apps.compliance.adapters import get_gsp_client
from apps.compliance.adapters.base import GspCredentials, GspError
from apps.compliance.models import GstCredential
from apps.platform.models import Tenant
from apps.platform.selectors import effective_features
from common.crypto import mask
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields
from common.tenancy import require_tenant_id, tenant_transaction

MODULES = ("einvoice", "ewaybill")
# The provider's own credential fields; the first two are required.
# TODO(verify): the chosen GSP's credential fields (PROGRESS pre-production item 18).
FIELDS: dict[str, tuple[str, ...]] = {
    "mock": ("username", "password", "client_id", "client_secret")
}
REQUIRED = 2


class NotReady(DomainError):
    status_code = 409
    code = ErrorCode.GST_CREDENTIALS_NOT_READY
    default_message = gettext_lazy("Enter and check your GST provider credentials first.")


def require_module() -> None:
    features = effective_features()
    if not any(features.get(code, False) for code in MODULES):
        raise DomainError(
            _("E-invoicing and e-way bills aren't switched on for your business."),
            code=ErrorCode.MODULE_NOT_ENABLED,
            status_code=403,
        )


def fields() -> tuple[str, ...]:
    return FIELDS.get(settings.GSP_PROVIDER, ())


def current() -> GstCredential | None:
    return GstCredential.objects.filter(provider=settings.GSP_PROVIDER).first()


def _values(row: GstCredential) -> dict[str, str]:
    return json.loads(row.credentials) if row.credentials else {}


def describe(row: GstCredential | None) -> dict[str, Any]:
    """What the settings screen shows: never a secret, only its last characters."""
    stored = _values(row) if row else {}
    return {
        "provider": settings.GSP_PROVIDER,
        "field_names": list(fields()),
        "required_fields": list(fields()[:REQUIRED]),
        "environment": row.environment if row else GstCredential.Environment.SANDBOX,
        "gstin": row.gstin if row else Tenant.objects.get(pk=require_tenant_id()).gstin,
        "saved": {name: mask(stored.get(name, "")) for name in fields()},
        "status": row.status if row else GstCredential.Status.UNVERIFIED,
        "verified_at": row.verified_at if row else None,
        "last_error": row.last_error if row else "",
    }


def save(environment: str, given: dict[str, str], *, by: User) -> GstCredential:
    """Save the credentials (blank fields keep the stored value) and start a check. Audited
    with the names of the fields that changed, never their values."""
    require_module()
    if environment not in GstCredential.Environment.values:
        raise InvalidFields({"environment": [_("Choose sandbox or production.")]})
    unknown = sorted(set(given) - set(fields()))
    if unknown:
        raise InvalidFields({name: ["Not a field of this provider."] for name in unknown})
    row = current() or GstCredential(provider=settings.GSP_PROVIDER)
    stored = _values(row)
    merged = {**stored, **{k: v.strip() for k, v in given.items() if v and v.strip()}}
    missing = [name for name in fields()[:REQUIRED] if not merged.get(name)]
    if missing:
        raise InvalidFields({name: ["This field is required."] for name in missing})
    changed = sorted(k for k in merged if merged.get(k) != stored.get(k))
    if row.environment != environment:
        changed.append("environment")
    row.environment = environment
    row.gstin = Tenant.objects.get(pk=require_tenant_id()).gstin
    row.credentials = json.dumps(merged, sort_keys=True)
    row.status, row.verified_at, row.last_error = GstCredential.Status.CHECKING, None, ""
    row.updated_by = by
    row.save()
    audit.record(
        "compliance.credentials_saved",
        target=row,
        target_repr=f"{row.provider} ({row.environment})",
        metadata={"changed": changed},
    )
    _check_after_commit(row)
    return row


def request_check() -> GstCredential:
    """Check the saved credentials again (the provider may have changed them)."""
    require_module()
    row = current()
    if row is None:
        raise NotReady()
    row.status, row.last_error = GstCredential.Status.CHECKING, ""
    row.save(update_fields=["status", "last_error", "updated_at"])
    _check_after_commit(row)
    return row


def _check_after_commit(row: GstCredential) -> None:
    from apps.compliance import tasks

    tenant_id = str(row.tenant_id)
    transaction.on_commit(
        lambda: tasks.verify_credentials.apply_async(kwargs={"tenant_id": tenant_id})
    )


def for_use(row: GstCredential) -> GspCredentials:
    return GspCredentials(row.provider, row.environment, row.gstin, _values(row))


def verify(tenant_id: Any) -> str:
    """Sign in with the provider (outside any transaction) and record the result."""
    with tenant_transaction(tenant_id):
        row = current()
        if row is None:
            return "none"
        given = for_use(row)
    try:
        get_gsp_client(given.provider).verify(given)
        outcome, error = GstCredential.Status.VERIFIED, ""
    except GspError as exc:
        outcome, error = GstCredential.Status.FAILED, exc.message[:300]
    with tenant_transaction(tenant_id):
        GstCredential.objects.filter(pk=row.pk).update(
            status=outcome,
            last_error=error,
            verified_at=timezone.now() if outcome == GstCredential.Status.VERIFIED else None,
            updated_at=timezone.now(),
        )
        audit.record(
            "compliance.credentials_checked",
            target=row,
            target_repr=f"{row.provider} ({row.environment})",
            changes={"status": [GstCredential.Status.CHECKING, outcome]},
            metadata={"error": error} if error else {},
        )
    return str(outcome)


def ready() -> GstCredential:
    """The verified credentials for sending documents, or NotReady."""
    row = current()
    if row is None or not row.is_active or row.status != GstCredential.Status.VERIFIED:
        raise NotReady()
    return row
