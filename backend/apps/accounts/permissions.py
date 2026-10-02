"""Permission registry and system roles (spec §2, PLAN §3.1).

Permissions are named codes grouped into roles, so custom roles can be added later without code
changes. This module is the source of truth: ``sync_permissions`` (run by migrations and the
``sync_permissions`` command) makes the database match it.
"""

from dataclasses import dataclass
from typing import Any

from django.utils.translation import gettext, gettext_noop


@dataclass(frozen=True)
class PermissionDef:
    code: str
    description: str

    @property
    def module(self) -> str:
        return self.code.split(".")[0] if not self.code.startswith("platform.") else "platform"


TENANT_PERMISSIONS: tuple[PermissionDef, ...] = (
    PermissionDef("settings.manage", "Business details, commercial settings, integrations"),
    PermissionDef("branding.manage", "Logo, colours and display name"),
    PermissionDef("staff.manage", "Invite staff, change roles, deactivate staff"),
    PermissionDef("audit.view", "View the audit log"),
    PermissionDef("products.view", "View products and categories"),
    PermissionDef(
        "products.manage", "Create and edit products, categories, brands, units, imports"
    ),
    PermissionDef("pricing.view", "View price lists and discounts"),
    PermissionDef("pricing.manage", "Change price lists, retailer prices and discounts"),
    # ADR-042: costs are separate from selling prices.
    PermissionDef("costs.view", "See cost prices, goods-receipt costs and stock value"),
    PermissionDef("costs.manage", "Change cost prices and complete goods-receipt costs"),
    PermissionDef("retailers.view", "View retailers"),
    PermissionDef("retailers.manage", "Create and edit retailers"),
    PermissionDef("credit.manage", "Credit limits and credit-hold approvals"),
    PermissionDef("stock.view", "View stock levels and movements"),
    PermissionDef("stock.inward", "Record stock received"),
    PermissionDef("stock.adjust", "Adjust stock with a reason"),
    # ADR-053: suppliers, purchase orders, reorder suggestions.
    PermissionDef("purchasing.view", "View suppliers, purchase orders and reorder suggestions"),
    PermissionDef(
        "purchasing.manage",
        "Manage suppliers and purchase orders, confirm over-receipts, refresh stock planning",
    ),
    PermissionDef("orders.view", "View orders"),
    PermissionDef("orders.manage", "Accept, reject, modify and cancel orders"),
    PermissionDef("orders.create_on_behalf", "Place orders for retailers"),
    PermissionDef("orders.fulfil", "Pack, dispatch and deliver"),
    PermissionDef("orders.allocate_backorder", "Allocate arriving stock to backorders"),
    PermissionDef("invoices.view", "View invoices and credit notes"),
    PermissionDef("invoices.manage", "Credit notes and invoice PDF regeneration"),
    PermissionDef("compliance.manage", "E-invoices and e-way bills"),
    PermissionDef("payments.view", "View payments"),
    PermissionDef("ledger.view", "View retailer ledgers and outstanding"),
    PermissionDef("payments.record", "Record payments"),
    PermissionDef(
        "payments.collect", "Record payments collected from own shops (until handed over)"
    ),
    PermissionDef("payments.reverse", "Reverse payments"),
    PermissionDef("ledger.adjust", "Post ledger adjustments"),
    PermissionDef("reports.sales", "Sales reports for all retailers"),
    PermissionDef("reports.sales_own", "Sales reports for own retailers only"),
    PermissionDef("reports.stock", "Stock reports"),
    PermissionDef("reports.financial", "Financial reports"),
    PermissionDef(
        "notifications.manage", "Notification rules, templates, delivery log, announcements"
    ),
    PermissionDef("dashboard.view", "Dashboard (content filtered by other permissions)"),
)

PLATFORM_PERMISSIONS: tuple[PermissionDef, ...] = (
    PermissionDef("platform.tenants.manage", "Create, edit, suspend and reactivate tenants"),
    PermissionDef("platform.plans.manage", "Plans and tenant subscriptions"),
    PermissionDef("platform.flags.manage", "Feature flags"),
    PermissionDef("platform.settings.manage", "Platform settings and tax masters"),
    PermissionDef("platform.impersonate", "Impersonate tenant users for support"),
    PermissionDef("platform.dashboard.view", "Platform dashboard"),
    PermissionDef("platform.audit.view", "All-tenant audit log and impersonation history"),
    PermissionDef("platform.support.read", "Read-only cross-tenant support access (future role)"),
)

ALL_PERMISSIONS: dict[str, PermissionDef] = {
    p.code: p for p in (*TENANT_PERMISSIONS, *PLATFORM_PERMISSIONS)
}

_ALL_TENANT = frozenset(p.code for p in TENANT_PERMISSIONS)


@dataclass(frozen=True)
class SystemRoleDef:
    code: str
    name: str
    permissions: frozenset[str]
    platform: bool = False


# fmt: off
_SALES = frozenset({
    "products.view", "pricing.view", "retailers.view", "retailers.manage", "stock.view",
    "orders.view", "orders.manage", "orders.create_on_behalf", "invoices.view", "payments.view",
    "payments.collect", "ledger.view", "reports.sales_own", "dashboard.view",
})
_WAREHOUSE = frozenset({
    "products.view", "stock.view", "stock.inward", "stock.adjust", "orders.view", "orders.fulfil",
    "orders.allocate_backorder", "reports.stock", "dashboard.view", "purchasing.view",
})
_ACCOUNTS = frozenset({
    "products.view", "pricing.view", "costs.view", "retailers.view", "credit.manage", "stock.view",
    "orders.view", "invoices.view", "invoices.manage", "compliance.manage", "payments.view",
    "ledger.view", "payments.record", "payments.reverse", "ledger.adjust", "reports.sales",
    "reports.financial", "dashboard.view", "purchasing.view",
})
# fmt: on
_OWNER_ONLY = {"settings.manage", "branding.manage", "staff.manage", "audit.view"}
# Sales staff's own-shop variants; the office holds the full permissions instead.
_SALES_ONLY = {"reports.sales_own", "payments.collect"}

SYSTEM_ROLES: tuple[SystemRoleDef, ...] = (
    # Names are stored in English and translated where the server writes them (role_label).
    SystemRoleDef("OWNER", gettext_noop("Owner"), _ALL_TENANT - _SALES_ONLY),
    SystemRoleDef("MANAGER", gettext_noop("Manager"), _ALL_TENANT - _OWNER_ONLY - _SALES_ONLY),
    SystemRoleDef("SALES", gettext_noop("Sales"), _SALES),
    SystemRoleDef("WAREHOUSE", gettext_noop("Warehouse"), _WAREHOUSE),
    SystemRoleDef("ACCOUNTS", gettext_noop("Accounts"), _ACCOUNTS),
    SystemRoleDef(
        "PLATFORM_ADMIN",
        gettext_noop("Super admin"),
        frozenset(p.code for p in PLATFORM_PERMISSIONS),
        platform=True,
    ),
)

SYSTEM_ROLE_CODES = frozenset(r.code for r in SYSTEM_ROLES)

_lookup = gettext  # system role names are listed above with gettext_noop


def role_label(role: Any) -> str:
    """A role's name in the active language: a system role's translated, a distributor's own
    role as they named it."""
    return _lookup(role.name) if role.is_system else str(role.name)


OWNER_ROLE = "OWNER"
PLATFORM_ADMIN_ROLE = "PLATFORM_ADMIN"


def sync_permissions(apps: Any) -> None:
    """Make Permission rows and system roles match this module (idempotent).

    Takes an app registry so data migrations can pass historical models. Permission rows are never
    deleted (custom roles may reference them); unknown codes are simply unused.
    """
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    by_code = {}
    for pdef in ALL_PERMISSIONS.values():
        perm, _ = Permission.objects.update_or_create(
            code=pdef.code, defaults={"module": pdef.module, "description": pdef.description}
        )
        by_code[pdef.code] = perm
    for rdef in SYSTEM_ROLES:
        role, _ = Role.objects.update_or_create(
            tenant=None,
            code=rdef.code,
            defaults={"name": rdef.name, "is_system": True, "is_platform": rdef.platform},
        )
        role.permissions.set([by_code[c] for c in sorted(rdef.permissions)])
