"""A distributor's payment gateway settings (ADR-049 items 7, 9 and 11): the super admin switches
the ``payments`` module on; the owner (``settings.manage``) enters the account's keys and the
webhook secret and checks them.

- Keys are encrypted and never returned: reads show the last characters, and a blank field on
  save keeps what is stored.
- Test keys only unless live payments are allowed here (``PAYMENTS_ALLOW_LIVE``, off outside
  production). Razorpay keys must match the mode (TODO(verify): the key prefixes).
- Saving starts a check in the background (``payments.verify_gateway``), so no request waits on
  the gateway; "Check" asks again.
- The webhook address to enter in the gateway's dashboard is shown with the settings.
"""

from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.payments.gateway import get_gateway
from apps.payments.gateway.base import GatewayError, GatewayKeys
from apps.payments.models import GatewayConfig
from apps.platform.models import Tenant
from apps.platform.selectors import is_feature_enabled
from common.crypto import mask
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields
from common.hosts import web_url
from common.tenancy import require_tenant_id, tenant_transaction

SECRETS = ("key_id", "key_secret", "webhook_secret")
KEY_PREFIX = {("RAZORPAY", "TEST"): "rzp_test_", ("RAZORPAY", "LIVE"): "rzp_live_"}
C = GatewayConfig


class NotReady(DomainError):
    status_code = 409
    code = ErrorCode.PAYMENT_GATEWAY_NOT_READY
    default_message = "Online payments aren't set up yet."


def require_module(tenant_id: Any = None) -> None:
    if not is_feature_enabled("payments", tenant_id or require_tenant_id()):
        raise DomainError(
            "Online payments aren't switched on for your business.",
            code=ErrorCode.MODULE_NOT_ENABLED,
            status_code=403,
        )


def providers() -> list[str]:
    allowed: list[str] = [C.Provider.RAZORPAY]
    if settings.ALLOW_MOCK_INTEGRATIONS:
        allowed.append(C.Provider.MOCK)
    return allowed


def current() -> GatewayConfig | None:
    found: GatewayConfig | None = GatewayConfig.objects.first()
    return found


def webhook_url(provider: str) -> str:
    token = Tenant.objects.filter(pk=require_tenant_id()).values_list("webhook_token", flat=True)
    return web_url(f"/api/v1/webhooks/payments/{provider.lower()}/{token.get()}/")


def describe(row: GatewayConfig | None) -> dict[str, Any]:
    provider = row.provider if row else (providers()[-1] if settings.DEBUG else C.Provider.RAZORPAY)
    return {
        "providers": providers(),
        "provider": provider,
        "mode": row.mode if row else C.Mode.TEST,
        "live_allowed": bool(settings.PAYMENTS_ALLOW_LIVE),
        "saved": {name: mask(getattr(row, name, "") or "") for name in SECRETS},
        "status": row.status if row else C.Status.UNVERIFIED,
        "verified_at": row.verified_at if row else None,
        "last_error": row.last_error if row else "",
        "webhook_url": webhook_url(provider),
    }


def save(provider: str, mode: str, given: dict[str, str], *, by: User) -> GatewayConfig:
    """Save the keys (blank fields keep the saved ones) and start a check. Audited with the names
    of the fields that changed, never their values."""
    require_module()
    errors: dict[str, list[str]] = {}
    if provider not in providers():
        errors["provider"] = ["Choose a payment gateway."]
    if mode not in C.Mode.values:
        errors["mode"] = ["Choose test or live."]
    elif mode == C.Mode.LIVE and not settings.PAYMENTS_ALLOW_LIVE:
        errors["mode"] = ["Live payments aren't allowed here: use test keys."]
    if errors:
        raise InvalidFields(errors)
    row = current() or GatewayConfig(provider=provider)
    changed = [name for name in SECRETS if given.get(name, "").strip()]
    if row.provider != provider or row.mode != mode:
        changed.append("provider" if row.provider != provider else "mode")
    for name in SECRETS:
        value = given.get(name, "").strip()
        if value:
            setattr(row, name, value)
    missing = [name for name in SECRETS if not getattr(row, name)]
    if missing:
        raise InvalidFields({name: ["This field is required."] for name in missing})
    prefix = KEY_PREFIX.get((provider, mode))
    if prefix and not row.key_id.startswith(prefix):
        raise InvalidFields({"key_id": [f"A {mode.lower()} key starts with {prefix}."]})
    row.provider, row.mode, row.updated_by = provider, mode, by
    row.status, row.verified_at, row.last_error = C.Status.CHECKING, None, ""
    row.save()
    audit.record(
        "payments.gateway_saved",
        target=row,
        target_repr=f"{row.get_provider_display()} ({row.mode})",
        metadata={"changed": sorted(changed)},
    )
    _check_after_commit(row)
    return row


def request_check() -> GatewayConfig:
    require_module()
    row = current()
    if row is None:
        raise NotReady()
    row.status, row.last_error = C.Status.CHECKING, ""
    row.save(update_fields=["status", "last_error", "updated_at"])
    _check_after_commit(row)
    return row


def _check_after_commit(row: GatewayConfig) -> None:
    from apps.payments import tasks

    tenant_id = str(row.tenant_id)
    transaction.on_commit(lambda: tasks.verify_gateway.apply_async(kwargs={"tenant_id": tenant_id}))


def keys_of(row: GatewayConfig) -> GatewayKeys:
    return GatewayKeys(row.provider, row.mode, row.key_id, row.key_secret, row.webhook_secret)


def verify(tenant_id: Any) -> str:
    """Sign in with the gateway (outside any transaction) and record the result."""
    with tenant_transaction(tenant_id):
        row = current()
        if row is None:
            return "none"
        keys = keys_of(row)
    try:
        get_gateway(keys.provider).verify(keys)
        outcome, error = C.Status.VERIFIED, ""
    except GatewayError as exc:
        outcome, error = C.Status.FAILED, exc.message[:300]
    with tenant_transaction(tenant_id):
        GatewayConfig.objects.filter(pk=row.pk).update(
            status=outcome,
            last_error=error,
            verified_at=timezone.now() if outcome == C.Status.VERIFIED else None,
            updated_at=timezone.now(),
        )
        audit.record(
            "payments.gateway_checked",
            target=row,
            target_repr=f"{row.get_provider_display()} ({row.mode})",
            changes={"status": [C.Status.CHECKING, outcome]},
            metadata={"error": error} if error else {},
        )
    return str(outcome)


def ready(tenant_id: Any = None) -> GatewayConfig:
    """The working gateway for taking payments, or NotReady."""
    require_module(tenant_id)
    row = current()
    if row is None or not row.is_active or row.status != C.Status.VERIFIED:
        raise NotReady()
    return row


def available(tenant_id: Any) -> bool:
    """Can shops pay online right now (the module on and a working gateway)?"""
    if not is_feature_enabled("payments", tenant_id):
        return False
    row = current()
    return row is not None and row.is_active and row.status == C.Status.VERIFIED
