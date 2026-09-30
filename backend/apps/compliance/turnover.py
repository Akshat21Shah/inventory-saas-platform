"""The distributor's declared annual turnover band (ADR-049 item 3): set by the owner in
Settings (while a compliance module is on) or by the super admin at any time; audited as a
settings change. It drives suggestions and warnings only."""

from typing import Any
from uuid import UUID

from apps.accounts.models import User
from apps.compliance import rules
from apps.platform import services as settings_services
from apps.platform.selectors import effective_features
from common.tenancy import tenant_context


def summary(tenant_id: UUID, band: str | None = None) -> dict[str, Any]:
    t = rules.turnover(tenant_id, band)
    features = effective_features(tenant_id)
    return {
        "turnover_band": t.band,
        "einvoice_suggested": t.einvoice_suggested,
        "reporting_limit_applies": t.reporting_limit_applies,
        "reporting_days": t.reporting_days,
        "einvoice_enabled": features.get("einvoice", False),
        "ewaybill_enabled": features.get("ewaybill", False),
    }


def set_band(tenant_id: UUID, band: str, *, by: User) -> dict[str, Any]:
    """The super admin's path (the owner's is the settings registry)."""
    with tenant_context(tenant_id):
        values = settings_services.set_tenant_settings(
            {"compliance.turnover_band": band}, user=by
        )  # fresh values: the cache is cleared only when this commits
        return summary(tenant_id, str(values["compliance.turnover_band"]))
