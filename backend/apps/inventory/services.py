"""Inventory write logic (PLAN §5, ADR-041). Every stock change goes through this module."""

from collections.abc import Iterable
from uuid import UUID

from django.db import connection

from apps.inventory.defaults import ensure_default_warehouse
from apps.inventory.models import StockLevel, Warehouse
from common.ids import uuid7
from common.tenancy import require_tenant_id


def default_warehouse() -> Warehouse:
    """The active tenant's default warehouse (created on first use for safety)."""
    warehouse: Warehouse = ensure_default_warehouse(Warehouse)
    return warehouse


def ensure_levels_exist(product_ids: Iterable[UUID], warehouse: Warehouse) -> None:
    """Create any missing stock level at zero (PLAN S6); safe under concurrency."""
    ids = sorted(set(product_ids))
    if not ids:
        return
    tenant_id = require_tenant_id()
    table = StockLevel._meta.db_table
    rows = [(uuid7(), tenant_id, product_id, warehouse.pk) for product_id in ids]
    with connection.cursor() as cursor:
        cursor.executemany(
            f"INSERT INTO {table} "  # noqa: S608
            "(id, tenant_id, product_id, warehouse_id, quantity_on_hand, quantity_reserved, "
            "quantity_backordered, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, 0, 0, 0, now(), now()) "
            "ON CONFLICT (product_id, warehouse_id) DO NOTHING",
            rows,
        )
