"""Per-tenant inventory defaults: every tenant has one default warehouse (ADR-041)."""

from typing import Any

DEFAULT_WAREHOUSE_CODE = "MAIN"
DEFAULT_WAREHOUSE_NAME = "Main warehouse"


def ensure_default_warehouse(warehouse_model: Any) -> Any:
    """Return the active tenant's default warehouse, creating it if missing (idempotent)."""
    existing = warehouse_model.objects.filter(is_default=True).first()
    if existing is not None:
        return existing
    return warehouse_model.objects.create(
        code=DEFAULT_WAREHOUSE_CODE, name=DEFAULT_WAREHOUSE_NAME, is_default=True
    )
