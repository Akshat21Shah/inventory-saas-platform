"""Settings registry (ADR-016, PLAN §9): every configurable business rule, defined once in code.

Only overrides are stored (``TenantSetting`` / ``PlatformSetting``); a missing row means the
default, so a new tenant works with zero rows. Values are validated here, read through
``platform.selectors.get_setting`` and written only through ``platform.services`` (audited).
The settings UI is generated from this registry (``settings/registry`` endpoints).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


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
    NOTIFICATIONS = "notifications"
    COMPLIANCE = "compliance"
    REPORTS = "reports"
    PLANNING = "planning"
    PURCHASING = "purchasing"
    AI = "ai"  # ADR-058: platform-wide AI limits
    LANGUAGES = "languages"  # ADR-060: which languages people may choose


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
    # Tenant settings of an optional module: shown and editable only while one of these feature
    # flags is on, so a distributor without the module sees nothing new (ADR-049 item 1).
    features: tuple[str, ...] = ()
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
        raise ValidationError(_("A value is required."), code="required")
    if defn.type is SettingType.BOOL:
        if not isinstance(value, bool):
            raise ValidationError(_("Choose on or off."), code="invalid_type")
        return value
    if defn.type is SettingType.INT:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(_("Enter a whole number."), code="invalid_type")
        if defn.allowed and value not in defn.allowed:
            raise ValidationError(_("Choose one of the listed options."), code="invalid_choice")
        _check_range(defn, value)
        return value
    if defn.type is SettingType.MONEY:
        if isinstance(value, (bool, float)):
            raise ValidationError(_("Enter an amount like 1500.00."), code="invalid_type")
        try:
            amount = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValidationError(_("Enter an amount like 1500.00."), code="invalid_type") from exc
        if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")):
            raise ValidationError(_("Use at most 2 decimal places."), code="invalid_type")
        _check_range(defn, amount)
        return amount.quantize(Decimal("0.01"))
    if defn.type is SettingType.ENUM:
        if value not in defn.allowed:
            raise ValidationError(_("Choose one of the listed options."), code="invalid_choice")
        if value in defn.reserved_values:
            raise ValidationError(_("This option is not available yet."), code="reserved_choice")
        return value
    if defn.type is SettingType.STRING:
        if not isinstance(value, str):
            raise ValidationError(_("Enter text."), code="invalid_type")
        if defn.pattern and not re.fullmatch(defn.pattern, value):
            raise ValidationError(
                _("This value is not in the expected format."), code="invalid_format"
            )
        return value
    raise AssertionError(f"unhandled setting type {defn.type}")


# Settings that must rise in this order: (lower, higher, the message).
ASCENDING: tuple[tuple[str, str, str], ...] = (
    (
        "planning.abc_a_percent",
        "planning.abc_b_percent",
        "The class B share must be higher than the class A share.",
    ),
)


def _check_range(defn: SettingDef, value: int | Decimal) -> None:
    if defn.min_value is not None and value < defn.min_value:
        raise ValidationError(
            _("Enter %(min_value)s or more.") % {"min_value": defn.min_value}, code="out_of_range"
        )
    if defn.max_value is not None and value > defn.max_value:
        raise ValidationError(
            _("Enter %(max_value)s or less.") % {"max_value": defn.max_value}, code="out_of_range"
        )


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


_CLOCK = r"([01]\d|2[0-3]):[0-5]\d"  # 24-hour, IST
_PRICE = r"\d{1,4}(\.\d{1,4})?"  # rupees, up to 4 decimals (WhatsApp prices are paise)


def _language_codes() -> tuple[str, ...]:
    from common.languages import codes

    return codes()


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
    # ADR-057 item 3: shops ask for returns from their app; staff approve each one.
    _tenant("returns.shop_requests", Group.INVOICING, SettingType.BOOL, True,
            "Let shops ask for returns from their app. You approve each one, which issues the "
            "credit note."),
    _tenant("returns.request_days", Group.INVOICING, SettingType.INT, 30,
            "How many days after a bill a shop can ask to return goods from it.",
            min_value=1, max_value=365, depends_on=DependsOn("returns.shop_requests", True)),
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
    # ADR-057: delivery confirmed by the shop, and an optional delivery code.
    _tenant("orders.shop_confirms_delivery", Group.ORDERS, SettingType.BOOL, True,
            "Let shops mark a dispatched shipment as received in their app."),
    _tenant("orders.delivery_code", Group.ORDERS, SettingType.BOOL, False,
            "Give each shipment a 4-digit code at dispatch. The shop gives it to the delivery "
            "person, who enters it to mark the shipment delivered."),
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
    _tenant("stock.show_out_of_stock_in_shop", Group.STOCK, SettingType.BOOL, True,
            "Show products with no stock to shops, marked \"Out of stock\". Turn off to hide them. "
            "Applies only when backorders are off (ADR-041).",
            depends_on=DependsOn("backorders.enabled", equals=False)),
    _tenant("stock.cost_method", Group.STOCK, SettingType.ENUM, "WEIGHTED_AVERAGE",
            "How goods receipts change a product's cost price: the average of your stock and the "
            "new bill, the latest bill cost, or never (you set it yourself) (ADR-041).",
            allowed=("WEIGHTED_AVERAGE", "LAST_PURCHASE", "MANUAL")),
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
    # ADR-057 item 4: an optional charge when a shop's cheque bounces (no GST; CA question 47).
    _tenant("payments.cheque_bounce_charge", Group.CREDIT_PAYMENTS, SettingType.MONEY,
            Decimal("0"),
            "Charge a shop this amount when its cheque bounces; ₹0 charges nothing. It is added "
            "to the shop's account, due at once, without GST.",
            min_value=Decimal("0"), max_value=Decimal("100000")),
    _tenant("payments.sales_can_collect", Group.CREDIT_PAYMENTS, SettingType.BOOL, True,
            "Let sales staff record payments they collect from their shops (tracked until handed "
            "over)."),
    _tenant("receivables.ageing_basis", Group.CREDIT_PAYMENTS, SettingType.ENUM, "INVOICE_DATE",
            "Age receivables by days since the invoice date, or by days past the due date.",
            allowed=("INVOICE_DATE", "DUE_DATE")),
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
    # ADR-060: the language of shops that haven't chosen one (their screens, messages and
    # documents); the choices are the manifest's languages, so a new language needs no code.
    _tenant("retailers.default_language", Group.RETAILERS, SettingType.ENUM, "en",
            "The language your shops see and get their messages and documents in, unless a "
            "shop chooses its own.",
            allowed=_language_codes()),
    # Shop activity and win-back (ADR-056): how shops are grouped.
    _tenant("insights.new_days", Group.RETAILERS, SettingType.INT, 30,
            "A shop counts as new for this many days after its first order.",
            min_value=7, max_value=120),
    _tenant("insights.dormant_days", Group.RETAILERS, SettingType.INT, 45,
            "A shop that hasn't ordered for this many days has stopped ordering.",
            min_value=14, max_value=365),
    _tenant("insights.slowing_percent", Group.RETAILERS, SettingType.INT, 150,
            "A shop is slowing down when it hasn't ordered for this share of its usual gap "
            "between orders (150% of 10 days: 15 days).", min_value=110, max_value=400),
    _tenant("insights.contact_snooze_days", Group.RETAILERS, SettingType.INT, 14,
            "After someone contacts a shop, it leaves the win-back list for this many days.",
            min_value=1, max_value=90),
    # --- Tenant: Reports (ADR-050) -------------------------------------------------------------
    _tenant("reports.movement_days", Group.REPORTS, SettingType.INT, 90,
            "The period for fast, slow and dead stock, in days.", min_value=7, max_value=365),
    _tenant("reports.fast_share_percent", Group.REPORTS, SettingType.INT, 20,
            "The share of products that sold, from the top, counted as fast-moving.",
            min_value=5, max_value=50),
    # --- Tenant: Stock planning (ADR-053; shown while the module is on) --------------------------
    _tenant("planning.demand_days", Group.PLANNING, SettingType.INT, 30,
            "Daily demand is the quantity ordered over this many days.",
            min_value=7, max_value=180, features=("stock_planning",)),
    _tenant("planning.safety_days", Group.PLANNING, SettingType.INT, 7,
            "Safety stock, in days of demand, kept for late deliveries and busy weeks.",
            min_value=0, max_value=60, features=("stock_planning",)),
    _tenant("planning.cover_days", Group.PLANNING, SettingType.INT, 14,
            "A suggested order covers this many days of demand after it arrives.",
            min_value=1, max_value=120, features=("stock_planning",)),
    _tenant("planning.default_lead_days", Group.PLANNING, SettingType.INT, 7,
            "Days from ordering to receiving, when the supplier doesn't say.",
            min_value=1, max_value=90, features=("stock_planning",)),
    _tenant("planning.abc_a_percent", Group.PLANNING, SettingType.INT, 80,
            "Class A: the top products making this share of sales value.",
            min_value=50, max_value=95, features=("stock_planning",)),
    _tenant("planning.abc_b_percent", Group.PLANNING, SettingType.INT, 95,
            "Class B: the next products, up to this share of sales value; the rest are C.",
            min_value=60, max_value=99, features=("stock_planning",)),
    # --- Tenant: Purchasing (ADR-053; shown while the module is on) -----------------------------
    _tenant("purchasing.over_receipt_tolerance_percent", Group.PURCHASING, SettingType.INT, 10,
            "Receiving more than ordered is accepted up to this share over the order; beyond it, "
            "someone who manages purchasing must confirm.",
            min_value=0, max_value=100, features=("purchasing",)),
    # --- Tenant: Security (ADR-030) -------------------------------------------------------------
    _tenant("security.require_staff_2fa", Group.SECURITY, SettingType.BOOL, False,
            "Require every staff member to set up two-step verification (an authenticator app) "
            "before they can sign in."),
    # --- Platform -------------------------------------------------------------------------------
    # ADR-058: AI features' cap, timeout and how near a meaning must be for search.
    _platform("platform.ai_monthly_units", Group.AI, SettingType.INT, 2_000_000,
              "Most AI units (tokens or characters, as the provider counts) a distributor may use "
              "in a calendar month; over it, AI features step aside. 0: no cap.",
              min_value=0, max_value=1_000_000_000),
    _platform("platform.ai_timeout_seconds", Group.AI, SettingType.INT, 5,
              "How long the app waits for the AI provider before working without it.",
              min_value=1, max_value=60),
    _platform("platform.ai_assistant_timeout_seconds", Group.AI, SettingType.INT, 30,
              "How long the data assistant waits for the AI provider on each step before "
              "giving up on the question (ADR-059).",
              min_value=5, max_value=120),
    # Owner review (ADR-059 item 8): the assistant's model, and the prices and typical sizes that
    # turn units into rupees, questions and searches. Prices are placeholders until checked with
    # the providers (pre-production items 38 and 40); the cap itself stays in units.
    _platform("platform.ai_assistant_model", Group.AI, SettingType.ENUM, "claude-sonnet-5-5",
              "The model the data assistant uses. Check its name and price with the provider "
              "before the assistant is switched on (pre-production item 40).",
              allowed=("claude-sonnet-5-5", "claude-haiku-4-5-20251001")),
    _platform("platform.ai_sonnet_price_in", Group.AI, SettingType.MONEY, Decimal("265.00"),
              "Claude Sonnet 5.5: rupees per million units sent to it (the question, the "
              "instructions and the figures).",
              min_value=Decimal("0"), max_value=Decimal("100000")),
    _platform("platform.ai_sonnet_price_out", Group.AI, SettingType.MONEY, Decimal("1325.00"),
              "Claude Sonnet 5.5: rupees per million units it writes back.",
              min_value=Decimal("0"), max_value=Decimal("100000")),
    _platform("platform.ai_haiku_price_in", Group.AI, SettingType.MONEY, Decimal("88.00"),
              "Claude Haiku 4.5: rupees per million units sent to it.",
              min_value=Decimal("0"), max_value=Decimal("100000")),
    _platform("platform.ai_haiku_price_out", Group.AI, SettingType.MONEY, Decimal("440.00"),
              "Claude Haiku 4.5: rupees per million units it writes back.",
              min_value=Decimal("0"), max_value=Decimal("100000")),
    _platform("platform.ai_embeddings_price", Group.AI, SettingType.MONEY, Decimal("2.00"),
              "Product search: rupees per million units sent to the embedding provider (₹0 when "
              "the model runs in our own containers).",
              min_value=Decimal("0"), max_value=Decimal("100000")),
    _platform("platform.ai_question_units_in", Group.AI, SettingType.INT, 5_700,
              "A typical assistant question: units sent to the model, over all its steps. Used "
              "to show the cap and usage as questions and rupees; set it from the evaluation "
              "run (pre-production item 40).",
              min_value=100, max_value=500_000),
    _platform("platform.ai_question_units_out", Group.AI, SettingType.INT, 300,
              "A typical assistant question: units the model writes back.",
              min_value=10, max_value=100_000),
    _platform("platform.ai_search_units", Group.AI, SettingType.INT, 20,
              "A typical shop search: units sent to the embedding provider.",
              min_value=1, max_value=10_000),
    _platform("platform.ai_search_min_similarity_percent", Group.AI, SettingType.INT, 35,
              "How close in meaning a product must be to what a shop typed to be shown after the "
              "keyword matches.",
              min_value=1, max_value=99),
    # ADR-060 item 12: the languages people may choose. Until a language's native review, it is
    # only for testing: super admins and the distributors listed below.
    _platform("platform.languages_enabled", Group.LANGUAGES, SettingType.STRING, "en",
              "Languages everyone may choose, by code, separated by commas, for example "
              "\"en,hi\". English is always on.",
              pattern=r"[a-z]{2,3}(,[a-z]{2,3})*"),
    _platform("platform.language_test_tenants", Group.LANGUAGES, SettingType.STRING, "",
              "Distributors (by web address name, separated by commas) whose staff and shops "
              "may use every language, to test languages that aren't enabled yet.",
              pattern=r"([a-z0-9-]+(,[a-z0-9-]+)*)?"),
    _platform("platform.hsn_rate_hints_enabled", Group.TAX, SettingType.BOOL, True,
              "Suggest GST rates from the HSN hint table on product forms and imports."),
    _platform("platform.default_invoice_prefix", Group.INVOICING, SettingType.STRING, "INV",
              "Prefix proposed when a tenant's first invoice series is created.",
              pattern=r"[A-Z0-9]{1,3}"),
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
    # --- Notifications (ADR-048) ---------------------------------------------------------------
    _tenant("notifications.quiet_hours_start", Group.NOTIFICATIONS, SettingType.STRING, "21:00",
            "From this time, reminders and other non-urgent WhatsApp, SMS and email messages wait "
            "until quiet hours end. In-app messages are never held.",
            pattern=_CLOCK),
    _tenant("notifications.quiet_hours_end", Group.NOTIFICATIONS, SettingType.STRING, "08:00",
            "When quiet hours end and held messages go out.",
            pattern=_CLOCK),
    _tenant("notifications.document_link_days", Group.NOTIFICATIONS, SettingType.INT, 30,
            "How many days a bill or receipt link sent by WhatsApp or email keeps working.",
            min_value=1, max_value=365),
    # The daily summary (ADR-056).
    _tenant("notifications.daily_summary_enabled", Group.NOTIFICATIONS, SettingType.BOOL, True,
            "Send a summary each morning: yesterday's orders, billing and collections, and what "
            "needs action. Who gets it, and how, is set under Who gets which message."),
    _tenant("notifications.daily_summary_time", Group.NOTIFICATIONS, SettingType.STRING, "08:00",
            "When the daily summary goes out (Indian time).", pattern=r"([01]\d|2[0-3]):[0-5]\d"),
    _tenant("notifications.daily_summary_skip_sunday", Group.NOTIFICATIONS, SettingType.BOOL,
            False, "Don't send the daily summary on Sundays."),
    _tenant("notifications.payment_reminder_days", Group.NOTIFICATIONS, SettingType.STRING,
            "-2,3,7,15,30",
            "Days to remind shops of their bills: a minus number is days before the due date, the "
            "others days after it.",
            pattern=r"-?\d{1,3}(,-?\d{1,3}){0,9}"),
    _tenant("notifications.payment_reminder_repeat_days", Group.NOTIFICATIONS, SettingType.INT,
            15, "After the last reminder day, remind again every this many days (0: stop).",
            min_value=0, max_value=90),
    _tenant("notifications.handover_reminder_days", Group.NOTIFICATIONS, SettingType.INT, 2,
            "Remind salesmen of collections not handed over after this many days.",
            min_value=1, max_value=30),
    # E-invoicing and e-way bills (Phase 7, ADR-049): thresholds are placeholders to verify.
    _tenant("compliance.turnover_band", Group.COMPLIANCE, SettingType.ENUM, "BELOW_5_CR",
            "The business's annual turnover band. It decides only suggestions and warnings: "
            "e-invoicing is suggested from ₹5 crore, the IRN reporting-limit warning shows from "
            "₹10 crore.", allowed=("BELOW_5_CR", "FROM_5_TO_10_CR", "FROM_10_CR"),
            features=("einvoice", "ewaybill")),
    _tenant("einvoice.auto_generate", Group.COMPLIANCE, SettingType.BOOL, True,
            "Get the IRN automatically when an invoice or credit note to a registered shop is "
            "issued. Off: staff get it with a button.", features=("einvoice",)),
    _tenant("ewaybill.threshold_inter_state", Group.COMPLIANCE, SettingType.MONEY,
            Decimal("50000.00"), "An e-way bill is made for goods going to another state when "
            "the invoice (with tax) is worth more than this (placeholder, to verify).",
            min_value=Decimal("0"), features=("ewaybill",)),
    _tenant("ewaybill.threshold_intra_state", Group.COMPLIANCE, SettingType.MONEY,
            Decimal("50000.00"), "An e-way bill is made for goods within the state when the "
            "invoice (with tax) is worth more than this; states set their own (placeholder).",
            min_value=Decimal("0"), features=("ewaybill",)),
    _tenant("ewaybill.auto_generate", Group.COMPLIANCE, SettingType.BOOL, True,
            "Make the e-way bill automatically at dispatch when the invoice needs one. Off: "
            "staff make it with a button.", features=("ewaybill",)),
    _platform("platform.einvoice_threshold_crore", Group.COMPLIANCE, SettingType.INT, 5,
              "E-invoicing is suggested for businesses with turnover from this many crore "
              "(to verify).", min_value=1, max_value=500),
    _platform("platform.irn_limit_threshold_crore", Group.COMPLIANCE, SettingType.INT, 10,
              "The IRN reporting-limit warning shows for businesses with turnover from this many "
              "crore (to verify).", min_value=1, max_value=500),
    _platform("platform.irn_reporting_days", Group.COMPLIANCE, SettingType.INT, 30,
              "Days from the document date within which an IRN must be obtained, for businesses "
              "above the reporting-limit threshold (to verify).", min_value=1, max_value=365),
    _platform("platform.irn_cancel_window_hours", Group.COMPLIANCE, SettingType.INT, 24,
              "Hours after the IRN within which it can be cancelled (to verify).",
              min_value=1, max_value=720),
    _platform("platform.report_async_rows", Group.REPORTS, SettingType.INT, 5000,
              "Report exports with more rows than this are made in the background, with a "
              "message when ready.", min_value=100, max_value=100000),
    _platform("platform.b2cl_threshold", Group.REPORTS, SettingType.MONEY, Decimal("100000"),
              "Bills to shops without a GSTIN in another state above this value are listed one "
              "by one in the GST summary (B2C large; to verify).", min_value=Decimal("0")),
    _platform("platform.report_link_days", Group.REPORTS, SettingType.INT, 7,
              "Days a background export can be downloaded before it is deleted.",
              min_value=1, max_value=30),
    _platform("platform.ewaybill_cancel_window_hours", Group.COMPLIANCE, SettingType.INT, 24,
              "Hours after an e-way bill within which it can be cancelled (to verify).",
              min_value=1, max_value=720),
    _platform("platform.whatsapp_price_utility", Group.NOTIFICATIONS, SettingType.STRING, None,
              "Price in rupees of one WhatsApp utility message (orders, bills, payments, "
              "reminders), for distributors' cost estimates.", pattern=_PRICE, nullable=True),
    _platform("platform.whatsapp_price_marketing", Group.NOTIFICATIONS, SettingType.STRING, None,
              "Price in rupees of one WhatsApp marketing message (announcements).",
              pattern=_PRICE, nullable=True),
    _platform("platform.whatsapp_price_authentication", Group.NOTIFICATIONS, SettingType.STRING,
              None, "Price in rupees of one WhatsApp authentication message (sign-in codes).",
              pattern=_PRICE, nullable=True),
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


def module_on(defn: SettingDef, features: Mapping[str, bool]) -> bool:
    """Is the setting's module switched on (always, for settings of no optional module)?"""
    return not defn.features or any(features.get(code, False) for code in defn.features)
