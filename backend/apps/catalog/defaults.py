"""Units every distributor starts with (editable per tenant)."""

from typing import Any

# (code, name, allows_decimal, GST UQC).
# TODO(verify): the UQC codes against the GST portal's Unit Quantity Code list before e-invoicing
# (Phase 7) and GSTR reports (Phase 8); they are printed on invoices.
DEFAULT_UNITS: tuple[tuple[str, str, bool, str], ...] = (
    ("PCS", "Pieces", False, "PCS"),
    ("NOS", "Numbers", False, "NOS"),
    ("BOX", "Box", False, "BOX"),
    ("CTN", "Carton", False, "CTN"),
    ("PKT", "Packet", False, "PAC"),
    ("DOZ", "Dozen", False, "DOZ"),
    ("BTL", "Bottle", False, "BTL"),
    ("SET", "Set", False, "SET"),
    ("KG", "Kilogram", True, "KGS"),
    ("G", "Gram", True, "GMS"),
    ("LTR", "Litre", True, "LTR"),
    ("ML", "Millilitre", True, "MLT"),
    ("MTR", "Metre", True, "MTR"),
)


def ensure_default_units(unit_model: Any) -> None:
    """Create any missing default unit in the active tenant (idempotent)."""
    from common.tenancy import require_tenant_id

    tenant_id = require_tenant_id()  # bulk_create skips TenantScopedModel.save
    existing = set(unit_model.objects.values_list("code", flat=True))
    unit_model.objects.bulk_create(
        [
            unit_model(tenant_id=tenant_id, code=code, name=name, allows_decimal=decimal, uqc=uqc)
            for code, name, decimal, uqc in DEFAULT_UNITS
            if code not in existing
        ]
    )
