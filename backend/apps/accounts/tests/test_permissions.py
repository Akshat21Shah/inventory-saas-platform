"""Permission registry, system roles and permission resolution (spec §2, PLAN §3.1)."""

import pytest
from django.apps import apps as django_apps
from django.db import IntegrityError, connection, transaction
from django.db.utils import ProgrammingError
from django.urls import URLPattern, URLResolver, get_resolver

from apps.accounts.models import Membership, Permission, Role
from apps.accounts.permissions import (
    ALL_PERMISSIONS,
    PLATFORM_PERMISSIONS,
    SYSTEM_ROLES,
    sync_permissions,
)
from apps.accounts.tests.factories import (
    make_membership,
    make_retailer_login,
    make_staff,
    make_staff_in,
    make_super_admin,
    system_role,
)
from common.permissions import codes_of
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db

OWN, MGR, SAL, WH, ACC = "OWNER", "MANAGER", "SALES", "WAREHOUSE", "ACCOUNTS"

# PLAN §3.1, transcribed literally: code → roles that hold it. A change on either side fails here.
PLAN_MATRIX: dict[str, set[str]] = {
    "settings.manage": {OWN},
    "branding.manage": {OWN},
    "staff.manage": {OWN},
    "audit.view": {OWN},
    "products.view": {OWN, MGR, SAL, WH, ACC},
    "products.manage": {OWN, MGR},
    "pricing.view": {OWN, MGR, SAL, ACC},
    "pricing.manage": {OWN, MGR},
    "costs.view": {OWN, MGR, ACC},  # ADR-042
    "costs.manage": {OWN, MGR},
    "retailers.view": {OWN, MGR, SAL, ACC},
    "retailers.manage": {OWN, MGR, SAL},
    "credit.manage": {OWN, MGR, ACC},
    "stock.view": {OWN, MGR, SAL, WH, ACC},
    "stock.inward": {OWN, MGR, WH},
    "stock.adjust": {OWN, MGR, WH},
    "orders.view": {OWN, MGR, SAL, WH, ACC},
    "orders.manage": {OWN, MGR, SAL},
    "orders.create_on_behalf": {OWN, MGR, SAL},
    "orders.fulfil": {OWN, MGR, WH},
    "orders.allocate_backorder": {OWN, MGR, WH},
    "invoices.view": {OWN, MGR, SAL, ACC},
    "invoices.manage": {OWN, MGR, ACC},
    "compliance.manage": {OWN, MGR, ACC},
    "payments.view": {OWN, MGR, SAL, ACC},
    "ledger.view": {OWN, MGR, SAL, ACC},
    "payments.record": {OWN, MGR, ACC},
    "payments.collect": {SAL},
    "payments.reverse": {OWN, MGR, ACC},
    "ledger.adjust": {OWN, MGR, ACC},
    "reports.sales": {OWN, MGR, ACC},
    "reports.sales_own": {SAL},
    "reports.stock": {OWN, MGR, WH},
    "reports.financial": {OWN, MGR, ACC},
    "notifications.manage": {OWN, MGR},
    "dashboard.view": {OWN, MGR, SAL, WH, ACC},
}


def _db_role_codes(role_code):
    return set(system_role(role_code).permissions.values_list("code", flat=True))


def test_registry_matches_plan_matrix():
    tenant_codes = {c for c in ALL_PERMISSIONS if not c.startswith("platform.")}
    assert tenant_codes == set(PLAN_MATRIX)


@pytest.mark.parametrize("role_code", [OWN, MGR, SAL, WH, ACC])
def test_system_role_permissions_match_plan(role_code):
    expected = {code for code, roles in PLAN_MATRIX.items() if role_code in roles}
    assert _db_role_codes(role_code) == expected


def test_platform_admin_has_every_platform_permission_and_no_tenant_ones():
    assert _db_role_codes("PLATFORM_ADMIN") == {p.code for p in PLATFORM_PERMISSIONS}


def test_database_matches_registry_and_sync_is_idempotent():
    sync_permissions(django_apps)
    sync_permissions(django_apps)
    assert set(Permission.objects.values_list("code", flat=True)) == set(ALL_PERMISSIONS)
    system = Role.objects.filter(tenant__isnull=True, is_system=True)
    assert set(system.values_list("code", flat=True)) == {r.code for r in SYSTEM_ROLES}


@pytest.mark.parametrize("role_code", [OWN, MGR, SAL, WH, ACC])
def test_staff_permissions_follow_membership_role(tenant_a, role_code):
    user = make_staff_in(tenant_a, role_code)
    with tenant_context(tenant_a.id):
        for code, roles in PLAN_MATRIX.items():
            assert user.has_permission_code(code) is (role_code in roles), code
        assert not user.has_permission_code("platform.tenants.manage")


def test_membership_in_one_tenant_grants_nothing_in_another(tenant_a, tenant_b):
    user = make_staff_in(tenant_a, OWN)
    with tenant_context(tenant_b.id):
        assert user.permission_codes() == frozenset()
        assert not user.has_permission_code("orders.view")


def test_one_user_can_hold_different_roles_in_different_tenants(tenant_a, tenant_b):
    user = make_staff_in(tenant_a, WH)
    make_membership(user, tenant_b, ACC)
    with tenant_context(tenant_a.id):
        assert user.has_permission_code("stock.adjust")
        assert not user.has_permission_code("payments.record")
    with tenant_context(tenant_b.id):
        assert user.has_permission_code("payments.record")
        assert not user.has_permission_code("stock.adjust")


def test_no_tenant_context_means_no_staff_permissions(tenant_a):
    user = make_staff_in(tenant_a, OWN)
    assert user.permission_codes() == frozenset()


def test_inactive_membership_or_user_has_no_permissions(tenant_a):
    user = make_staff()
    make_membership(user, tenant_a, OWN, is_active=False)
    with tenant_context(tenant_a.id):
        assert user.permission_codes() == frozenset()
    active = make_staff_in(tenant_a, OWN)
    active.is_active = False
    with tenant_context(tenant_a.id):
        assert not active.has_permission_code("orders.view")


def test_super_admin_gets_platform_permissions_only(tenant_a):
    admin = make_super_admin()
    assert admin.platform_role == system_role("PLATFORM_ADMIN")
    assert admin.has_permission_code("platform.tenants.manage")
    assert admin.has_permission_code("platform.impersonate")
    with tenant_context(tenant_a.id):
        assert not admin.has_permission_code("orders.view")


def test_retailer_users_have_no_staff_permissions(tenant_a):
    retailer = make_retailer_login(tenant_a)
    with tenant_context(tenant_a.id):
        assert retailer.permission_codes() == frozenset()


def test_platform_role_is_only_for_platform_users():
    with pytest.raises(IntegrityError), transaction.atomic():
        make_staff(platform_role=system_role("PLATFORM_ADMIN"))


def test_role_code_unique_even_for_system_roles(tenant_a):
    with pytest.raises(IntegrityError), transaction.atomic():
        Role.objects.create(
            code="OWNER", name="dup system role"
        )  # (NULL, code): nulls not distinct
    Role.objects.create(tenant=tenant_a, code="OWNER", name="tenant custom role may reuse a code")


def test_platform_role_requires_no_tenant(tenant_a):
    with pytest.raises(IntegrityError), transaction.atomic():
        Role.objects.create(tenant=tenant_a, code="SUPPORT", name="Support", is_platform=True)


def test_system_role_requires_no_tenant(tenant_a):
    with pytest.raises(IntegrityError), transaction.atomic():
        Role.objects.create(tenant=tenant_a, code="CUSTOM", name="Custom", is_system=True)


def test_one_membership_per_user_and_tenant(tenant_a):
    user = make_staff_in(tenant_a, OWN)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_membership(user, tenant_a, MGR)


def _as_app_user(cursor, tenant_id):
    cursor.execute("SET LOCAL ROLE app_user")
    cursor.execute("SELECT set_config('app.current_tenant', %s, true)", [str(tenant_id)])


def test_rls_system_roles_readable_by_every_tenant_but_not_writable(tenant_a):
    with transaction.atomic(), connection.cursor() as cursor:
        _as_app_user(cursor, tenant_a.id)
        cursor.execute("SELECT count(*) FROM accounts_role WHERE tenant_id IS NULL")
        assert cursor.fetchone()[0] == len(SYSTEM_ROLES)
        cursor.execute("RESET ROLE")
    with pytest.raises(ProgrammingError), transaction.atomic(), connection.cursor() as cursor:
        _as_app_user(cursor, tenant_a.id)
        cursor.execute(
            "INSERT INTO accounts_role (id, created_at, updated_at, tenant_id, code, name, "
            "is_system, is_platform) VALUES (gen_random_uuid(), now(), now(), NULL, 'EVIL', 'x', "
            "true, false)"
        )


def test_rls_memberships_are_isolated(tenant_a, tenant_b):
    make_staff_in(tenant_a, OWN)
    make_staff_in(tenant_b, OWN)
    with transaction.atomic(), connection.cursor() as cursor:
        _as_app_user(cursor, tenant_a.id)
        cursor.execute("SELECT DISTINCT tenant_id FROM accounts_membership")
        assert [r[0] for r in cursor.fetchall()] == [tenant_a.id]
        cursor.execute("RESET ROLE")


def test_membership_is_tenant_scoped_model(tenant_a):
    make_staff_in(tenant_a, OWN)
    with tenant_context(tenant_a.id):
        assert Membership.objects.count() == 1


def _view_classes():
    def walk(patterns):
        for p in patterns:
            if isinstance(p, URLResolver):
                yield from walk(p.url_patterns)
            elif isinstance(p, URLPattern):
                cls = getattr(p.callback, "view_class", None) or getattr(p.callback, "cls", None)
                if cls is not None:
                    yield str(p.pattern), cls

    return list(walk(get_resolver().url_patterns))


def test_every_declared_endpoint_permission_is_a_registered_code():
    """A typo in ``required_permission`` would silently lock an endpoint (fail closed); catch it."""
    for route, cls in _view_classes():
        declared = []
        if getattr(cls, "required_permission", None):
            declared.append(cls.required_permission)
        declared.extend((getattr(cls, "required_permissions", None) or {}).values())
        for code in (c for requirement in declared for c in codes_of(requirement)):
            assert code in ALL_PERMISSIONS, f"{route}: unknown permission code {code!r}"


@pytest.mark.urls("common.tests.urls")
def test_has_permission_allows_the_role_in_its_tenant_only(api_client_for, tenant_a, tenant_b):
    owner = make_staff_in(tenant_a, OWN)
    warehouse = make_staff_in(tenant_a, WH)
    assert api_client_for(owner, tenant_a).get("/test-api/guarded/").status_code == 200
    assert api_client_for(warehouse, tenant_a).get("/test-api/guarded/").status_code == 403
    # No membership in tenant B: the session itself is rejected there.
    cross = api_client_for(owner, tenant_b, ensure_membership=False).get("/test-api/guarded/")
    assert cross.status_code == 401
