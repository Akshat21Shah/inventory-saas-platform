"""Settings registry, typed reads and audited writes (ADR-016, PLAN §9.3)."""

from decimal import Decimal

import pytest
from django.core.cache import cache
from django.db import connection, transaction

from apps.audit.models import AuditLog
from apps.platform import registry, selectors, services
from apps.platform.models import PlatformSetting, TenantSetting
from apps.platform.registry import Scope, SettingType, SnapshotOn
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db

TENANT_KEYS = [d.key for d in registry.definitions(Scope.TENANT)]
PLATFORM_KEYS = [d.key for d in registry.definitions(Scope.PLATFORM)]


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


# --- Registry self-tests (PLAN §9.3) ------------------------------------------------------------


@pytest.mark.parametrize("key", list(registry.REGISTRY))
def test_every_default_is_valid_for_its_definition(key):
    defn = registry.REGISTRY[key]
    assert registry.to_python(defn, defn.default) == defn.default
    json_value = registry.to_json(defn, defn.default)
    assert registry.from_json(defn, json_value) == defn.default


@pytest.mark.parametrize("key", list(registry.REGISTRY))
def test_every_key_is_documented_and_well_formed(key):
    defn = registry.REGISTRY[key]
    assert defn.description.strip().endswith(".")
    assert len(defn.description) >= 20
    assert defn.i18n_key == f"settings.{key}.description"
    prefix = key.split(".")[0]
    assert (prefix == "platform") == (defn.scope is Scope.PLATFORM)
    if defn.type is SettingType.ENUM:
        assert defn.allowed and set(defn.reserved_values) <= set(defn.allowed)
        assert defn.default not in defn.reserved_values
    if defn.depends_on is not None:
        assert defn.depends_on.key in registry.REGISTRY
        assert registry.REGISTRY[defn.depends_on.key].scope is defn.scope


def test_required_permissions_follow_scope():
    for defn in registry.REGISTRY.values():
        expected = "platform.settings.manage" if defn.scope is Scope.PLATFORM else "settings.manage"
        assert defn.required_permission == expected


def test_registry_covers_plan_catalogue():
    # PLAN §9.1 (27) + security.require_staff_2fa (ADR-030) + retailers.blocked_can_sign_in and
    # pricing.discounts_on_special_prices (ADR-036) + pricing.discount_combination (ADR-038)
    # + stock.show_out_of_stock_in_shop, stock.cost_method (ADR-041)
    # + payments.sales_can_collect, receivables.ageing_basis (ADR-046)
    # + 6 notifications settings (ADR-048) + turnover band, automatic IRNs, e-way bill
    # thresholds and automatic e-way bills (ADR-049) + the fast/slow/dead period and share (ADR-050)
    # + 6 stock planning settings and the over-receipt tolerance (ADR-053)
    assert len(TENANT_KEYS) == 65  # + activity, summary (ADR-056), delivery (ADR-057)
    # PLAN §9.2 (3) + 7 login/OTP limits (ADR-030) + reset limit + 3 WhatsApp prices (ADR-048)
    # + 2 e-invoicing thresholds, the IRN reporting limit and cancellation window, the e-way
    # bill cancellation window (ADR-049) + the export row limit, link days and the B2C large
    # threshold (ADR-050)
    assert len(PLATFORM_KEYS) == 22
    assert "security.require_staff_2fa" in TENANT_KEYS
    assert registry.REGISTRY["retailers.blocked_can_sign_in"].default is True
    assert registry.REGISTRY["pricing.discounts_on_special_prices"].default is True


def test_spec_defaults():
    """Spec §13 defaults, so a new tenant behaves as specified."""
    d = {k: registry.REGISTRY[k].default for k in registry.REGISTRY}
    assert d["tax.prices_include_gst"] is False
    assert d["stock.show_exact_quantity"] is False
    assert d["backorders.enabled"] is True
    assert d["backorders.allocation_mode"] == "CONFIRM"
    assert d["credit.breach_action"] == "REQUIRE_APPROVAL"
    assert d["invoicing.timing"] == "ON_DISPATCH"
    assert d["orders.acceptance_mode"] == "MANUAL"
    assert d["orders.min_order_value"] is None
    assert d["backorders.billing_price"] == "ORIGINAL"
    assert d["orders.staff_can_place_on_behalf"] is True
    assert d["orders.sales_visibility"] == "ALL"
    assert d["credit.hold_reserves_stock"] is True
    assert d["payments.hold_advances"] is True
    assert d["payments.cheque_credit_timing"] == "ON_RECEIPT"
    assert d["security.require_staff_2fa"] is False
    assert d["platform.login_rate_per_ip_per_minute"] == 30
    assert d["platform.otp_rate_per_ip_per_hour"] == 100
    assert d["platform.password_reset_per_email_per_hour"] == 3


# --- Validation ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("tax.prices_include_gst", True, True),
        ("invoicing.default_payment_terms_days", 0, 0),
        ("invoicing.default_payment_terms_days", 365, 365),
        ("orders.min_order_value", "1500", Decimal("1500.00")),
        ("orders.min_order_value", "0.50", Decimal("0.50")),
        ("orders.min_order_value", None, None),
        ("tax.hsn_min_digits", 8, 8),
        ("platform.default_invoice_prefix", "SD2", "SD2"),
    ],
)
def test_valid_values(key, value, expected):
    assert registry.to_python(registry.REGISTRY[key], value) == expected


@pytest.mark.parametrize(
    ("key", "value", "code"),
    [
        ("tax.prices_include_gst", "yes", "invalid_type"),
        ("tax.prices_include_gst", None, "required"),
        ("invoicing.default_payment_terms_days", 366, "out_of_range"),
        ("invoicing.default_payment_terms_days", -1, "out_of_range"),
        ("invoicing.default_payment_terms_days", True, "invalid_type"),
        ("invoicing.default_payment_terms_days", 30.0, "invalid_type"),
        ("orders.min_order_value", 1500.0, "invalid_type"),  # floats never carry money
        ("orders.min_order_value", "10.005", "invalid_type"),
        ("orders.min_order_value", "-1", "out_of_range"),
        ("orders.min_order_value", "NaN", "invalid_type"),
        ("tax.hsn_min_digits", 5, "invalid_choice"),
        ("orders.acceptance_mode", "SOMETIMES", "invalid_choice"),
        ("tax.registration_type", "COMPOSITION", "reserved_choice"),
        ("platform.default_invoice_prefix", "inv", "invalid_format"),
        ("platform.default_invoice_prefix", "SD24", "invalid_format"),  # numbers ≤ 16 chars
    ],
)
def test_invalid_values(key, value, code):
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError) as exc:
        registry.to_python(registry.REGISTRY[key], value)
    assert exc.value.code == code


# --- Reads --------------------------------------------------------------------------------------


def test_fresh_tenant_resolves_every_key_to_its_default(tenant_a):
    """PLAN §9.3: a tenant with zero overrides works on defaults."""
    values = selectors.tenant_settings(tenant_a.id)
    assert set(values) == set(TENANT_KEYS)
    for key, value in values.items():
        assert value == registry.REGISTRY[key].default
    for key in TENANT_KEYS:
        assert selectors.get_setting(key, tenant_a.id) == registry.REGISTRY[key].default


def test_platform_keys_resolve_to_defaults():
    assert selectors.platform_settings() == {k: registry.REGISTRY[k].default for k in PLATFORM_KEYS}


def test_get_setting_rejects_unknown_key_and_wrong_scope(tenant_a):
    with pytest.raises(KeyError):
        selectors.get_setting("orders.nope", tenant_a.id)
    with pytest.raises(KeyError):
        selectors.get_setting("platform.login_lockout_minutes", tenant_a.id)
    with pytest.raises(KeyError):
        selectors.get_platform_setting("orders.acceptance_mode")


# --- Writes -------------------------------------------------------------------------------------


def test_set_stores_override_audits_and_isolates_tenants(tenant_a, tenant_b, staff_user):
    with tenant_context(tenant_a.id):
        result = services.set_tenant_settings(
            {"orders.acceptance_mode": "AUTO", "orders.min_order_value": "2500"}, user=staff_user
        )
    assert result["orders.acceptance_mode"] == "AUTO"
    assert result["orders.min_order_value"] == Decimal("2500.00")
    assert selectors.get_setting("orders.acceptance_mode", tenant_a.id) == "AUTO"
    assert selectors.get_setting("orders.min_order_value", tenant_a.id) == Decimal("2500.00")
    assert selectors.get_setting("orders.acceptance_mode", tenant_b.id) == "MANUAL"

    stored = TenantSetting.objects.unscoped().get(tenant=tenant_a, key="orders.min_order_value")
    assert stored.value == "2500.00"  # money stored as a string
    assert stored.updated_by == staff_user

    entries = AuditLog.objects.filter(tenant=tenant_a, action="settings.changed").order_by(
        "target_id"
    )
    assert [(e.target_id, e.changes) for e in entries] == [
        ("orders.acceptance_mode", {"value": ["MANUAL", "AUTO"]}),
        ("orders.min_order_value", {"value": [None, "2500.00"]}),
    ]


def test_unchanged_value_is_not_audited(tenant_a, staff_user):
    with tenant_context(tenant_a.id):
        services.set_tenant_settings({"orders.acceptance_mode": "MANUAL"}, user=staff_user)
    assert not AuditLog.objects.filter(action="settings.changed").exists()
    assert not TenantSetting.objects.unscoped().exists()


def test_setting_back_to_default_removes_override(tenant_a, staff_user):
    with tenant_context(tenant_a.id):
        services.set_tenant_settings({"backorders.enabled": False}, user=staff_user)
        services.set_tenant_settings({"backorders.enabled": True}, user=staff_user)
    assert not TenantSetting.objects.unscoped().filter(key="backorders.enabled").exists()
    assert AuditLog.objects.filter(action="settings.changed").count() == 2


def test_batch_is_all_or_nothing_with_field_errors(tenant_a, staff_user):
    with tenant_context(tenant_a.id), pytest.raises(services.SettingsInvalid) as exc:
        services.set_tenant_settings(
            {
                "orders.acceptance_mode": "AUTO",
                "orders.pending_alert_hours": 0,
                "tax.registration_type": "COMPOSITION",
                "orders.unknown": 1,
                "platform.login_lockout_minutes": 5,
            },
            user=staff_user,
        )
    fields = exc.value.details["fields"]
    assert set(fields) == {
        "orders.pending_alert_hours",
        "tax.registration_type",
        "orders.unknown",
        "platform.login_lockout_minutes",  # platform keys are not tenant settings
    }
    assert exc.value.code == "VALIDATION_ERROR"
    assert not TenantSetting.objects.unscoped().exists()
    assert not AuditLog.objects.exists()


def test_reset_restores_default_and_audits(tenant_a, staff_user):
    with tenant_context(tenant_a.id):
        services.set_tenant_settings({"stock.show_exact_quantity": True}, user=staff_user)
        assert services.reset_tenant_setting("stock.show_exact_quantity", user=staff_user) is False
        services.reset_tenant_setting("stock.show_exact_quantity", user=staff_user)  # no-op
    entry = AuditLog.objects.get(action="settings.reset")
    assert entry.changes == {"value": [True, False]}
    assert selectors.get_setting("stock.show_exact_quantity", tenant_a.id) is False


def test_cache_is_invalidated_only_after_commit(
    tenant_a, staff_user, django_capture_on_commit_callbacks
):
    assert selectors.get_setting("orders.acceptance_mode", tenant_a.id) == "MANUAL"  # cached
    with django_capture_on_commit_callbacks(execute=True), tenant_context(tenant_a.id):
        services.set_tenant_settings({"orders.acceptance_mode": "AUTO"}, user=staff_user)
        # Before commit, other readers still see the committed (cached) value.
        assert selectors.get_setting("orders.acceptance_mode", tenant_a.id) == "MANUAL"
    assert selectors.get_setting("orders.acceptance_mode", tenant_a.id) == "AUTO"


def test_rolled_back_write_never_reaches_the_cache(tenant_a, staff_user):
    with pytest.raises(RuntimeError), transaction.atomic(), tenant_context(tenant_a.id):
        services.set_tenant_settings({"orders.acceptance_mode": "AUTO"}, user=staff_user)
        raise RuntimeError("rollback")
    assert selectors.get_setting("orders.acceptance_mode", tenant_a.id) == "MANUAL"


def test_platform_settings_write_platform_level_audit(
    staff_user, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        services.set_platform_settings({"platform.login_lockout_minutes": 30}, user=staff_user)
    assert selectors.get_platform_setting("platform.login_lockout_minutes") == 30
    assert PlatformSetting.objects.get().value == 30
    entry = AuditLog.objects.get(action="settings.changed")
    assert entry.tenant_id is None
    assert entry.changes == {"value": [15, 30]}
    with pytest.raises(services.SettingsInvalid):
        services.set_platform_settings({"orders.acceptance_mode": "AUTO"}, user=staff_user)


# --- Snapshots (ADR-016) ------------------------------------------------------------------------


def test_snapshot_contains_exactly_the_snapshot_keys(tenant_a, staff_user):
    with tenant_context(tenant_a.id):
        services.set_tenant_settings({"orders.min_order_value": "100"}, user=staff_user)
    for target in SnapshotOn:
        snap = selectors.settings_snapshot(target, tenant_a.id)
        expected = {d.key for d in registry.definitions(Scope.TENANT) if target in d.snapshot_on}
        assert set(snap) == expected
    order = selectors.settings_snapshot(SnapshotOn.ORDER, tenant_a.id)
    assert order["tax.prices_include_gst"] is False
    assert order["backorders.billing_price"] == "ORIGINAL"
    assert "orders.min_order_value" not in order  # evaluated live at placement, not snapshotted
    assert selectors.settings_snapshot(SnapshotOn.PAYMENT, tenant_a.id) == {
        "payments.cheque_credit_timing": "ON_RECEIPT"
    }


def test_snapshot_is_json_safe_and_detached_from_later_changes(
    tenant_a, staff_user, django_capture_on_commit_callbacks
):
    import json

    snap = selectors.settings_snapshot(SnapshotOn.INVOICE, tenant_a.id)
    json.dumps(snap)
    with django_capture_on_commit_callbacks(execute=True), tenant_context(tenant_a.id):
        services.set_tenant_settings({"invoicing.round_to_rupee": False}, user=staff_user)
    assert snap["invoicing.round_to_rupee"] is True
    assert (
        selectors.settings_snapshot(SnapshotOn.INVOICE, tenant_a.id)["invoicing.round_to_rupee"]
        is False
    )


def test_tenant_settings_are_protected_by_rls(tenant_a, tenant_b, staff_user):
    with tenant_context(tenant_a.id):
        services.set_tenant_settings({"orders.acceptance_mode": "AUTO"}, user=staff_user)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE app_user")
        cursor.execute("SELECT set_config('app.current_tenant', %s, true)", [str(tenant_b.id)])
        cursor.execute("SELECT count(*) FROM platform_tenantsetting")
        assert cursor.fetchone()[0] == 0
        cursor.execute("RESET ROLE")
