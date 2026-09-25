from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.utils import ProgrammingError

from apps.audit import selectors, services
from apps.audit.models import AuditLog
from common.context import Actor, RequestMeta, actor_var, request_id_var, request_meta_var
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


@pytest.fixture
def as_actor(staff_user):
    token = actor_var.set(Actor(user_id=staff_user.pk, actor_type="STAFF"))
    yield staff_user
    actor_var.reset(token)


@pytest.fixture
def request_context():
    tokens = (
        request_meta_var.set(RequestMeta(ip="203.0.113.7", user_agent="pytest-agent")),
        request_id_var.set("req-123"),
    )
    yield
    request_meta_var.reset(tokens[0])
    request_id_var.reset(tokens[1])


def test_record_captures_tenant_actor_and_request(tenant_a, as_actor, request_context):
    with tenant_context(tenant_a.id):
        entry = services.record(
            "tenant.updated",
            target=tenant_a,
            changes={"name": ["Old", "New"]},
            metadata={"amount": Decimal("10.50"), "on": date(2026, 9, 25)},
        )
    entry.refresh_from_db()
    assert entry.tenant_id == tenant_a.id
    assert entry.actor_id == as_actor.pk
    assert entry.actor_type == "STAFF"
    assert (entry.target_type, entry.target_id, entry.target_repr) == (
        "platform.tenant",
        str(tenant_a.pk),
        str(tenant_a),
    )
    assert entry.changes == {"name": ["Old", "New"]}
    assert entry.metadata == {"amount": "10.50", "on": "2026-09-25"}
    assert (entry.ip, entry.user_agent, entry.request_id) == (
        "203.0.113.7",
        "pytest-agent",
        "req-123",
    )


def test_platform_level_entry_has_no_tenant(as_actor):
    entry = services.record(
        "tax_rate.deactivated", target_type="platform.taxrate", target_id="x", tenant_id=None
    )
    assert entry.tenant_id is None


def test_explicit_tenant_overrides_context(tenant_a, tenant_b, as_actor):
    with tenant_context(tenant_a.id):
        entry = services.record("tenant.suspended", target=tenant_b, tenant_id=tenant_b.id)
    assert entry.tenant_id == tenant_b.id


def test_without_actor_it_is_a_system_entry(tenant_a):
    with tenant_context(tenant_a.id):
        entry = services.record("stock.alert_raised")
    assert (entry.actor_id, entry.actor_type) == (None, "SYSTEM")


def test_impersonation_context_is_recorded(tenant_a, staff_user, django_user_model):
    admin = django_user_model.objects.create_superuser("root@example.com", "a-strong-password")
    session_id = uuid4()
    token = actor_var.set(
        Actor(
            user_id=staff_user.pk,
            actor_type="STAFF",
            impersonator_id=admin.pk,
            impersonation_session_id=session_id,
        )
    )
    try:
        with tenant_context(tenant_a.id):
            entry = services.record("orders.accepted")
    finally:
        actor_var.reset(token)
    assert entry.actor_id == staff_user.pk
    assert entry.impersonator_id == admin.pk
    assert entry.impersonation_session_id == session_id


def test_system_entry_requires_no_actor_but_others_do(tenant_a):
    with pytest.raises(IntegrityError), transaction.atomic():
        AuditLog.objects.create(tenant=tenant_a, actor_type="STAFF", action="x")


def test_entries_are_append_only(tenant_a, as_actor):
    with tenant_context(tenant_a.id):
        entry = services.record("tenant.updated")
    table = AuditLog._meta.db_table
    for statement in (
        f"UPDATE {table} SET action = 'tampered' WHERE id = %s",  # noqa: S608
        f"DELETE FROM {table} WHERE id = %s",  # noqa: S608
    ):
        with (
            pytest.raises(IntegrityError, match="append-only"),
            transaction.atomic(),
            connection.cursor() as c,
        ):
            c.execute(statement, [entry.pk])
    entry.refresh_from_db()
    assert entry.action == "tenant.updated"


def test_entry_is_rolled_back_with_the_business_transaction(tenant_a, as_actor):
    with pytest.raises(RuntimeError), transaction.atomic(), tenant_context(tenant_a.id):
        services.record("tenant.updated")
        raise RuntimeError("business failure")
    assert not AuditLog.objects.filter(action="tenant.updated").exists()


def _as_app_user(cursor, tenant_id):
    cursor.execute("SET LOCAL ROLE app_user")
    cursor.execute(
        "SELECT set_config('app.current_tenant', %s, true)", [str(tenant_id) if tenant_id else ""]
    )


def test_rls_tenant_sees_only_own_rows_and_never_platform_rows(tenant_a, tenant_b, as_actor):
    with tenant_context(tenant_a.id):
        services.record("a.action")
    with tenant_context(tenant_b.id):
        services.record("b.action")
    services.record("platform.action", tenant_id=None)
    with transaction.atomic(), connection.cursor() as cursor:
        _as_app_user(cursor, tenant_a.id)
        cursor.execute(f"SELECT action FROM {AuditLog._meta.db_table}")  # noqa: S608
        assert [r[0] for r in cursor.fetchall()] == ["a.action"]
        cursor.execute("RESET ROLE")


def test_rls_runtime_role_can_write_platform_and_own_rows_only(tenant_a, tenant_b, as_actor):
    """record() works for the runtime role; a raw insert into another tenant is refused."""
    with transaction.atomic(), connection.cursor() as cursor:
        _as_app_user(cursor, tenant_a.id)
        services.record("own.action")
        services.record("platform.action", tenant_id=None)
        services.record(
            "cross.action", tenant_id=tenant_b.id
        )  # switches the RLS tenant for the row
        cursor.execute("RESET ROLE")
    with pytest.raises(ProgrammingError), transaction.atomic(), connection.cursor() as cursor:
        _as_app_user(cursor, tenant_a.id)
        columns = (
            "id, created_at, updated_at, tenant_id, actor_type, action, target_type, target_id, "
            "target_repr, changes, metadata, user_agent, request_id"
        )
        values = (
            "gen_random_uuid(), now(), now(), %s, 'SYSTEM', 'forged', "
            "'', '', '', '{}', '{}', '', ''"
        )
        cursor.execute(
            f"INSERT INTO {AuditLog._meta.db_table} ({columns}) VALUES ({values})",  # noqa: S608
            [tenant_b.id],
        )


def test_tenant_audit_logs_is_isolated_and_filterable(tenant_a, tenant_b, as_actor):
    with tenant_context(tenant_a.id):
        services.record(
            "settings.changed", target_type="setting", target_id="orders.acceptance_mode"
        )
        services.record(
            "settings.reset", target_type="setting", target_id="stock.show_exact_quantity"
        )
        services.record("staff.invited")
    with tenant_context(tenant_b.id):
        services.record("settings.changed")
    services.record("tenant.suspended", tenant_id=tenant_a.id)  # platform action on tenant A

    with tenant_context(tenant_a.id):
        assert selectors.tenant_audit_logs().count() == 4
        assert selectors.tenant_audit_logs({"action": "settings."}).count() == 2
        assert selectors.tenant_audit_logs({"action": "settings.changed"}).count() == 1
        assert selectors.tenant_audit_logs({"target_id": "orders.acceptance_mode"}).count() == 1
        assert selectors.tenant_audit_logs({"actor_id": as_actor.pk}).count() == 4
        newest_first = list(selectors.tenant_audit_logs().values_list("action", flat=True))
        assert newest_first[0] == "tenant.suspended"


@pytest.mark.django_db(transaction=True, databases=["default", "platform"])
def test_platform_audit_logs_sees_every_tenant_and_platform_entries(tenant_a, tenant_b, staff_user):
    token = actor_var.set(Actor(user_id=staff_user.pk, actor_type="PLATFORM"))
    try:
        with transaction.atomic():
            with tenant_context(tenant_a.id):
                services.record("a.action")
            with tenant_context(tenant_b.id):
                services.record("b.action")
            services.record("platform.action", tenant_id=None)
        actions = set(selectors.platform_audit_logs().values_list("action", flat=True))
        assert actions == {"a.action", "b.action", "platform.action"}
        assert list(
            selectors.platform_audit_logs(tenant_id=tenant_b.id).values_list("action", flat=True)
        ) == ["b.action"]
    finally:
        actor_var.reset(token)


def test_diff_reports_changed_fields_only_and_masks_secrets():
    before = {
        "name": "A",
        "rate": Decimal("5.000"),
        "bank_account_number": "123456789012",
        "same": 1,
    }
    after = {
        "name": "B",
        "rate": Decimal("18.000"),
        "bank_account_number": "999988887777",
        "same": 1,
    }
    changes = services.diff(before, after, masked={"bank_account_number"})
    assert changes == {
        "bank_account_number": ["••••9012", "••••7777"],
        "name": ["A", "B"],
        "rate": ["5.000", "18.000"],
    }


def test_snapshot_reads_attnames(tenant_a):
    assert services.snapshot(tenant_a, ["name", "state_id"]) == {
        "name": tenant_a.name,
        "state_id": "27",
    }
