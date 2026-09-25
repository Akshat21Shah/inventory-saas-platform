"""Celery base task for tenant work: the tenant is passed explicitly, never inferred (ADR-002)."""

from typing import Any
from uuid import UUID

from celery import Task
from django.db import transaction

from common.tenancy import tenant_context


class TenantTask(Task):  # type: ignore[type-arg]
    """Requires a ``tenant_id`` kwarg; runs the task in a transaction with RLS tenant set.

    Tasks that call external services should set ``atomic = False`` and open short transactions
    themselves via ``tenant_transaction(tenant_id)`` so no DB transaction is held during I/O.
    """

    abstract = True
    atomic = True

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raw = kwargs.get("tenant_id")
        if not raw:
            raise ValueError(f"{self.name} requires tenant_id")
        tenant_id = UUID(str(raw))
        if not self.atomic:
            with tenant_context(tenant_id):
                return super().__call__(*args, **kwargs)
        with transaction.atomic(), tenant_context(tenant_id):
            return super().__call__(*args, **kwargs)
