"""Settings registry (ADR-016, PLAN §9): every configurable business rule, defined once in code.

Only overrides are stored (``TenantSetting`` / ``PlatformSetting``); a missing row means the
default, so a new tenant works with zero rows. Values are validated here, read through
``platform.selectors.get_setting`` and written only through ``platform.services`` (audited).
The settings UI is generated from this registry (``settings/registry`` endpoints).
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from django.core.exceptions import ValidationError


class Scope(StrEnum):
    TENANT = "TENANT"
    PLATFORM = "PLATFORM"


class Group(StrEnum):
    TAX = "tax"
    INVOICING = "invoicing"
    ORDERS = "orders"
    STOCK = "stock"
    CREDIT_PAYMENTS = "credit_payments"
    PRICING = "pricing"
    RETAILERS = "retailers"
    SECURITY = "security"


class SettingType(StrEnum):
    BOOL = "bool"
    INT = "int"
    ENUM = "enum"
    MONEY = "money"
    STRING = "string"


class SnapshotOn(StrEnum):
    ORDER = "ORDER"
    INVOICE = "INVOICE"
    CREDIT_NOTE = "CREDIT_NOTE"
    PAYMENT = "PAYMENT"


class Status(StrEnum):
    ACTIVE = "ACTIVE"
    RESERVED = "RESERVED"  # defined for the future; cannot be changed yet


@dataclass(frozen=True)
class DependsOn:
    """UI enable condition: ``key`` equals ``equals``, or (``not_null``) has any value."""

    key: str
    equals: Any = None
    not_null: bool = False


@dataclass(frozen=True)
class SettingDef:
    key: str
    group: Group
    scope: Scope
    type: SettingType
    default: Any
    description: str
    allowed: tuple[Any, ...] = ()  # ENUM values, or the only allowed INT values
    reserved_values: tuple[str, ...] = ()  # ENUM values shown but not selectable yet
    min_value: int | Decimal | None = None
    max_value: int | Decimal | None = None
    pattern: str | None = None  # STRING
    nullable: bool = False
    edit_permission: str = ""
    snapshot_on: frozenset[SnapshotOn] = field(default_factory=frozenset)
    depends_on: DependsOn | None = None
    status: Status = Status.ACTIVE

    @property
    def i18n_key(self) -> str:
        return f"settings.{self.key}.description"

    @property
    def required_permission(self) -> str:
        if self.edit_permission:
            return self.edit_permission
        return "platform.settings.manage" if self.scope is Scope.PLATFORM else "settings.manage"


def _to_python(defn: SettingDef, value: Any) -> Any:
    """Validate ``value`` (from JSON or Python) and return the typed Python value."""
    if value is None:
        if defn.nullable:
            return None
        raise ValidationError("A value is required.", code="required")
    if defn.type is SettingType.BOOL:
        if not isinstance(value, bool):
            raise ValidationError("Choose on or off.", code="invalid_type")
        return value
    if defn.type is SettingType.INT:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError("Enter a whole number.", code="invalid_type")
        if defn.allowed and value not in defn.allowed:
            raise ValidationError("Choose one of the listed options.", code="invalid_choice")
        _check_range(defn, value)
        return value
    if defn.type is SettingType.MONEY:
        if isinstance(value, (bool, float)):
            raise ValidationError("Enter an amount like 1500.00.", code="invalid_type")
        try:
            amount = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValidationError("Enter an amount like 1500.00.", code="invalid_type") from exc
        if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")):
            raise ValidationError("Use at most 2 decimal places.", code="invalid_type")
        _check_range(defn, amount)
        return amount.quantize(Decimal("0.01"))
    if defn.type is SettingType.ENUM:
        if value not in defn.allowed:
            raise ValidationError("Choose one of the listed options.", code="invalid_choice")
        if value in defn.reserved_values:
            raise ValidationError("This option is not available yet.", code="reserved_choice")
        return value
    if defn.type is SettingType.STRING:
        if not isinstance(value, str):
            raise ValidationError("Enter text.", code="invalid_type")
        if defn.pattern and not re.fullmatch(defn.pattern, value):
            raise ValidationError(
                "This value is not in the expected format.", code="invalid_format"
            )
        return value
    raise AssertionError(f"unhandled setting type {defn.type}")


def _check_range(defn: SettingDef, value: int | Decimal) -> None:
    if defn.min_value is not None and value < defn.min_value:
        raise ValidationError(f"Enter {defn.min_value} or more.", code="out_of_range")
    if defn.max_value is not None and value > defn.max_value:
        raise ValidationError(f"Enter {defn.max_value} or less.", code="out_of_range")


def to_python(defn: SettingDef, value: Any) -> Any:
    return _to_python(defn, value)


def to_json(defn: SettingDef, value: Any) -> Any:
    """Typed value → JSON-storable value (money as a string, never a float)."""
    if value is None:
        return None
    if defn.type is SettingType.MONEY:
        return str(Decimal(value).quantize(Decimal("0.01")))
    return value


def from_json(defn: SettingDef, stored: Any) -> Any:
    """Stored JSON → typed value. Stored values were validated on write."""
    if stored is None:
        return None
    if defn.type is SettingType.MONEY:
        return Decimal(str(stored))
    return stored


def _tenant(
    key: str, group: Group, type_: SettingType, default: Any, description: str, **kw: Any
) -> SettingDef:
    return SettingDef(
        key=key,
        group=group,
        scope=Scope.TENANT,
        type=type_,
        default=default,
        description=description,
        **kw,
    )


def _platform(
    key: str, group: Group, type_: SettingType, default: Any, description: str, **kw: Any
) -> SettingDef:
    return SettingDef(
        key=key,
        group=group,
        scope=Scope.PLATFORM,
        type=type_,
        default=default,
        description=description,
        **kw,
    )


_ORDER = frozenset({SnapshotOn.ORDER})
_ESTIMATE_AND_DOCS = frozenset({SnapshotOn.ORDER, SnapshotOn.INVOICE, SnapshotOn.CREDIT_NOTE})

# fmt: off
_DEFINITIONS: tuple[SettingDef, ...] = (
    # --- Tenant: Tax ----------------------------------------------------------------------------
    _tenant("tax.registration_type", Group.TAX, SettingType.ENUM, "REGULAR",
            "Your GST registration type. Only regular registration is supported now.",
            allowed=("REGULAR", "COMPOSITION"), reserved_values=("COMPOSITION",),
            snapshot_on=frozenset({SnapshotOn.ORDER, SnapshotOn.INVOICE})),
    _tenant("tax.prices_include_gst", Group.TAX, SettingType.BOOL, False,
            "Turn on if the prices you enter already include GST.", snapshot_on=_ORDER),
    _tenant("tax.component_rounding", Group.TAX, SettingType.ENUM, "HALF_UP",
            "How each tax amount is rounded to the paisa.",
            allowed=("HALF_UP", "HALF_EVEN"), snapshot_on=_ESTIMATE_AND_DOCS),
    _tenant("tax.hsn_min_digits", Group.TAX, SettingType.INT, 4,
            "Minimum HSN code length required on products.", allowed=(4, 6, 8)),
    # --- Tenant: Invoicing ----------------------------------------------------------------------
    _tenant("invoicing.timing", Group.INVOICING, SettingType.ENUM, "ON_DISPATCH",
            "When the tax invoice is created: when goods are dispatched (for the packed quantity), "
            "or when the order or backorder is accepted.",
            allowed=("ON_DISPATCH", "ON_ACCEPTANCE"), snapshot_on=_ORDER),
    _tenant("invoicing.round_to_rupee", Group.INVOICING, SettingType.BOOL, True,
            "Round invoice totals to the nearest rupee with a round-off line.",
            snapshot_on=_ESTIMATE_AND_DOCS),
    _tenant("invoicing.round_off_method", Group.INVOICING, SettingType.ENUM, "NEAREST",
            "How the invoice total is rounded to the rupee.",
            allowed=("NEAREST", "UP", "DOWN"), snapshot_on=_ESTIMATE_AND_DOCS,
            depends_on=DependsOn("invoicing.round_to_rupee", equals=True)),
    _tenant("invoicing.default_payment_terms_days", Group.INVOICING, SettingType.INT, 30,
            "Default credit days for new retailers (each retailer can differ).",
            min_value=0, max_value=365),
    # --- Tenant: Orders -------------------------------------------------------------------------
    _tenant("orders.acceptance_mode", Group.ORDERS, SettingType.ENUM, "MANUAL",
            "Accept new orders yourself, or automatically when they pass all checks.",
            allowed=("MANUAL", "AUTO"), snapshot_on=_ORDER),
    _tenant("orders.send_confirmation_on_accept", Group.ORDERS, SettingType.BOOL, True,
            "Send the retailer an Order Confirmation (items, prices, tax estimate) when you accept "
            "an order.", snapshot_on=_ORDER),
    _tenant("orders.min_order_value", Group.ORDERS, SettingType.MONEY, None,
            "Smallest order value a retailer can place. Backordered items count.",
            nullable=True, min_value=Decimal("0")),
    _tenant("orders.min_order_value_basis", Group.ORDERS, SettingType.ENUM, "INCL_GST",
            "Whether the minimum order value includes GST.",
            allowed=("INCL_GST", "EXCL_GST"),
            depends_on=DependsOn("orders.min_order_value", not_null=True)),
    _tenant("orders.pre_acceptance_edit_mode", Group.ORDERS, SettingType.ENUM, "REDUCE_ONLY",
            "What your team can change before accepting: only reduce or remove items, or also add "
            "items and increase quantities. The retailer is always notified.",
            allowed=("REDUCE_ONLY", "FULL_EDIT"), snapshot_on=_ORDER),
    _tenant("orders.staff_can_place_on_behalf", Group.ORDERS, SettingType.BOOL, True,
            "Allow your staff (for example salesmen) to place orders for retailers."),
    _tenant("orders.sales_visibility", Group.ORDERS, SettingType.ENUM, "ALL",
            "Which orders and retailers sales staff can see.",
            allowed=("ALL", "ASSIGNED_RETAILERS")),
    _tenant("orders.pending_alert_hours", Group.ORDERS, SettingType.INT, 24,
            "Show a dashboard alert for orders not accepted within this many hours.",
            min_value=1, max_value=168),
    _tenant("orders.insufficient_stock_action", Group.ORDERS, SettingType.ENUM, "FAIL",
            "When backorders are off and stock runs short at checkout: stop the order and show "
            "what's short, or place only the in-stock part.",
            allowed=("FAIL", "PLACE_AVAILABLE"),
            depends_on=DependsOn("backorders.enabled", equals=False)),
    # --- Tenant: Stock --------------------------------------------------------------------------
    _tenant("stock.show_exact_quantity", Group.STOCK, SettingType.BOOL, False,
            "Show retailers the exact quantity in stock (otherwise only \"In stock\" or "
            "\"Low stock\")."),
    _tenant("stock.show_low_stock_label", Group.STOCK, SettingType.BOOL, True,
            "Show a \"Low stock\" label to retailers when stock is at or below the reorder level."),
    _tenant("backorders.enabled", Group.STOCK, SettingType.BOOL, True,
            "Let retailers order more than is in stock; the rest is sent when stock arrives.",
            snapshot_on=_ORDER),
    _tenant("backorders.allocation_mode", Group.STOCK, SettingType.ENUM, "CONFIRM",
            "When stock arrives, confirm each backorder allocation yourself, or allocate "
            "automatically (oldest orders first).", allowed=("CONFIRM", "AUTO")),
    _tenant("backorders.billing_price", Group.STOCK, SettingType.ENUM, "ORIGINAL",
            "Price for backordered items sent later: the price when ordered, or today's price.",
            allowed=("ORIGINAL", "CURRENT"), snapshot_on=_ORDER),
    # --- Tenant: Credit & Payments --------------------------------------------------------------
    _tenant("credit.breach_action", Group.CREDIT_PAYMENTS, SettingType.ENUM, "REQUIRE_APPROVAL",
            "When an order would exceed a retailer's credit limit: hold it for approval, or refuse "
            "it.", allowed=("REQUIRE_APPROVAL", "BLOCK")),
    _tenant("credit.hold_reserves_stock", Group.CREDIT_PAYMENTS, SettingType.BOOL, True,
            "Keep stock reserved for orders waiting for credit approval.", snapshot_on=_ORDER),
    _tenant("credit.block_overdue_after_days", Group.CREDIT_PAYMENTS, SettingType.INT, None,
            "Treat a retailer as over limit when any invoice is overdue by more than this many "
            "days.", nullable=True, min_value=1, max_value=365),
    _tenant("payments.hold_advances", Group.CREDIT_PAYMENTS, SettingType.BOOL, True,
            "Keep extra money paid by a retailer as credit and use it for their next invoices."),
    _tenant("payments.cheque_credit_timing", Group.CREDIT_PAYMENTS, SettingType.ENUM, "ON_RECEIPT",
            "Credit a cheque to the retailer's account when received (reversed automatically if "
            "it bounces) or only when it clears.",
            allowed=("ON_RECEIPT", "ON_CLEARANCE"), snapshot_on=frozenset({SnapshotOn.PAYMENT})),
    # --- Tenant: Pricing (ADR-036) --------------------------------------------------------------
    _tenant("pricing.discounts_on_special_prices", Group.PRICING, SettingType.BOOL, True,
            "Apply discount rules on top of a shop's special prices. Turn off to treat a special "
            "price as the final price."),
    _tenant("pricing.discount_combination", Group.PRICING, SettingType.ENUM, "BEST",
            "When several discounts apply to a product: the best single one, add them together, "
            "or apply one after another from the most specific (ADR-038).",
            allowed=("BEST", "ADD", "SEQUENTIAL")),
    # --- Tenant: Retailers (ADR-036) ------------------------------------------------------------
    _tenant("retailers.blocked_can_sign_in", Group.RETAILERS, SettingType.BOOL, True,
            "Shops you put on hold can still sign in and see their account, but can't order. "
            "Turn off to stop them signing in."),
    _tenant("retailers.show_own_brand_badge", Group.RETAILERS, SettingType.BOOL, False,
            "Show an \"own brand\" badge on your own-brand products in the shop (ADR-039)."),
    # --- Tenant: Security (ADR-030) -------------------------------------------------------------
    _tenant("security.require_staff_2fa", Group.SECURITY, SettingType.BOOL, False,
            "Require every staff member to set up two-step verification (an authenticator app) "
            "before they can sign in."),
    # --- Platform -------------------------------------------------------------------------------
    _platform("platform.hsn_rate_hints_enabled", Group.TAX, SettingType.BOOL, True,
              "Suggest GST rates from the HSN hint table on product forms and imports."),
    _platform("platform.default_invoice_prefix", Group.INVOICING, SettingType.STRING, "INV",
              "Prefix proposed when a tenant's first invoice series is created.",
              pattern=r"[A-Z0-9]{1,6}"),
    _platform("platform.impersonation_session_minutes", Group.SECURITY, SettingType.INT, 30,
              "Maximum length of a support impersonation session.", min_value=5, max_value=60),
    _platform("platform.login_lockout_threshold", Group.SECURITY, SettingType.INT, 5,
              "Consecutive failed sign-ins before an account is locked.",
              min_value=3, max_value=20),
    _platform("platform.login_lockout_minutes", Group.SECURITY, SettingType.INT, 15,
              "How long a locked account stays locked.", min_value=1, max_value=1440),
    _platform("platform.login_rate_per_ip_per_minute", Group.SECURITY, SettingType.INT, 30,
              "Sign-in attempts allowed per minute from one IP address (generous: many mobile "
              "users share an IP).", min_value=5, max_value=1000),
    _platform("platform.login_rate_per_email_per_minute", Group.SECURITY, SettingType.INT, 5,
              "Sign-in attempts allowed per minute for one email address.",
              min_value=1, max_value=60),
    _platform("platform.otp_rate_per_phone_per_10_minutes", Group.SECURITY, SettingType.INT, 3,
              "OTP codes that can be requested for one phone number in 10 minutes.",
              min_value=1, max_value=20),
    _platform("platform.otp_rate_per_ip_per_hour", Group.SECURITY, SettingType.INT, 100,
              "OTP codes that can be requested from one IP address per hour (generous: many mobile "
              "users share an IP).", min_value=10, max_value=5000),
    _platform("platform.password_reset_per_email_per_hour", Group.SECURITY, SettingType.INT, 3,
              "Password reset emails that can be requested for one email address per hour.",
              min_value=1, max_value=20),
    _platform("platform.otp_max_verify_attempts", Group.SECURITY, SettingType.INT, 5,
              "Wrong codes allowed before an OTP stops working.", min_value=3, max_value=10),
)
# fmt: on

REGISTRY: dict[str, SettingDef] = {d.key: d for d in _DEFINITIONS}
if len(REGISTRY) != len(_DEFINITIONS):  # pragma: no cover - import-time guard
    raise RuntimeError("duplicate setting key in the registry")


def get_definition(key: str, scope: Scope | None = None) -> SettingDef:
    """The definition of ``key``; raises ``KeyError`` for unknown keys or the wrong scope."""
    defn = REGISTRY.get(key)
    if defn is None or (scope is not None and defn.scope is not scope):
        raise KeyError(key)
    return defn


def definitions(scope: Scope) -> list[SettingDef]:
    return [d for d in _DEFINITIONS if d.scope is scope]
