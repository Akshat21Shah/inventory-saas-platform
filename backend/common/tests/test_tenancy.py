from decimal import Decimal

import pytest
from django.db import connection, transaction
from django.db.utils import IntegrityError, ProgrammingError

from common.models import CrossTenantWrite, TenantScopedModel
from common.tenancy import TenantContextMissing, set_db_tenant, tenant_context
from common.tests.testapp.models import LedgerLike, Widget

pytestmark = pytest.mark.django_db


def test_manager_fails_closed_without_tenant():
    with pytest.raises(TenantContextMissing):
        list(Widget.objects.all())


def test_manager_filters_by_active_tenant(tenant_a, tenant_b):
    with tenant_context(tenant_a.id):
        Widget.objects.create(name="a1", price=Decimal("10.50"))
    with tenant_context(tenant_b.id):
        Widget.objects.create(name="b1")
        assert list(Widget.objects.values_list("name", flat=True)) == ["b1"]
    with tenant_context(tenant_a.id):
        widget = Widget.objects.get()
        assert widget.name == "a1"
        assert widget.tenant_id == tenant_a.id
        assert widget.price == Decimal("10.50")
    assert Widget.objects.unscoped().count() == 2


def test_save_rejects_cross_tenant_write(tenant_a, tenant_b):
    with tenant_context(tenant_a.id):
        widget = Widget.objects.create(name="a1")
    with tenant_context(tenant_b.id), pytest.raises(CrossTenantWrite):
        widget.name = "hijacked"
        widget.save()


def test_set_db_tenant_requires_transaction(transactional_db):
    with pytest.raises(RuntimeError):
        set_db_tenant(None)


def _as_app_user(cursor, tenant_id):
    cursor.execute("SET LOCAL ROLE app_user")
    cursor.execute(
        "SELECT set_config('app.current_tenant', %s, true)", [str(tenant_id) if tenant_id else ""]
    )


def test_rls_backstop_hides_other_tenants_rows(tenant_a, tenant_b):
    """Even a raw query without the ORM filter only sees the current tenant's rows."""
    with tenant_context(tenant_a.id):
        Widget.objects.create(name="a1")
    with tenant_context(tenant_b.id):
        Widget.objects.create(name="b1")
    table = Widget._meta.db_table
    with transaction.atomic(), connection.cursor() as cursor:
        _as_app_user(cursor, tenant_a.id)
        cursor.execute(f"SELECT name FROM {table}")  # noqa: S608
        assert [r[0] for r in cursor.fetchall()] == ["a1"]
        _as_app_user(cursor, None)
        cursor.execute(f"SELECT count(*) FROM {table}")  # noqa: S608
        assert cursor.fetchone()[0] == 0
        cursor.execute("RESET ROLE")


def test_rls_with_check_blocks_writing_into_another_tenant(tenant_a, tenant_b):
    table = Widget._meta.db_table
    with pytest.raises(ProgrammingError), transaction.atomic(), connection.cursor() as cursor:
        _as_app_user(cursor, tenant_a.id)
        cursor.execute(
            f"INSERT INTO {table} (id, tenant_id, name, price, qty, created_at, updated_at) "  # noqa: S608
            "VALUES (gen_random_uuid(), %s, 'x', 0, 0, now(), now())",
            [tenant_b.id],
        )


def _concrete_tenant_models():
    from django.apps import apps

    return [
        m
        for m in apps.get_models()
        if issubclass(m, TenantScopedModel) and not m._meta.abstract and m._meta.managed
    ]


def test_every_tenant_table_has_rls_enabled_and_policy():
    """Safety net: a new TenantScopedModel without EnableRLS in its migration fails CI."""
    models = _concrete_tenant_models()
    assert models, "expected at least one tenant-scoped model"
    with connection.cursor() as cursor:
        for model in models:
            table = model._meta.db_table
            cursor.execute("SELECT relrowsecurity FROM pg_class WHERE relname = %s", [table])
            assert cursor.fetchone()[0], f"RLS not enabled on {table}"
            cursor.execute("SELECT count(*) FROM pg_policies WHERE tablename = %s", [table])
            assert cursor.fetchone()[0] >= 1, f"no RLS policy on {table}"


def test_append_only_table_rejects_update_and_delete():
    row = LedgerLike.objects.create(note="entry")
    for statement in (
        f"UPDATE {LedgerLike._meta.db_table} SET note = 'changed'",  # noqa: S608
        f"DELETE FROM {LedgerLike._meta.db_table}",  # noqa: S608
    ):
        with (
            pytest.raises(IntegrityError, match="append-only"),
            transaction.atomic(),
            connection.cursor() as c,
        ):
            c.execute(statement)
    assert LedgerLike.objects.get(pk=row.pk).note == "entry"


def test_tenant_context_does_not_mask_database_errors(tenant_a):
    """A DB error inside the block surfaces as itself, not as a failed restore of the setting."""
    with pytest.raises(IntegrityError), transaction.atomic(), tenant_context(tenant_a.id):
        Widget.objects.create(name="a")
        with connection.cursor() as cursor:
            cursor.execute(f"INSERT INTO {Widget._meta.db_table} (id) VALUES (NULL)")  # noqa: S608
