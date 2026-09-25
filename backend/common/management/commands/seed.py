"""Demo data loader: the super admin, two demo distributors with complete business details, one
staff login per role in each, and demo shops. Phase 2 adds catalog, retailers and pricing.

Refuses to run unless DEBUG is on. Idempotent. Every password, phone number and the super admin's
2FA key below are public demo values for local development and E2E only.
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from apps.accounts.mfa import DEV_TOTP_SECRET
from apps.accounts.models import Membership, Role, User
from apps.accounts.permissions import PLATFORM_ADMIN_ROLE
from apps.platform.models import Plan, Subscription, Tenant, TenantBranding, TenantProfile
from apps.platform.validators import gstin_check_char
from apps.retailers.models import Retailer
from apps.retailers.services import create_retailer
from common.tenancy import tenant_context

STAFF_ROLES = ("OWNER", "MANAGER", "SALES", "WAREHOUSE", "ACCOUNTS")
# One shop per distributor, plus one phone number registered with both (the chooser on sign-in).
DEMO_SHOPS: dict[str, list[tuple[str, str, str]]] = {
    "sharma": [("Ganesh Kirana", "Ganesh Patil", "9876500001")],
    "patel": [("Shree Stores", "Mehul Shah", "9876500002")],
}
SHARED_SHOP = ("Om Provision Store", "Omkar Joshi", "9876500000")

# Demo identities are fictitious; GSTINs are generated to be checksum-valid.
DEMO_TENANTS: list[dict[str, str]] = [
    {
        "slug": "sharma",
        "name": "Sharma Distributors",
        "legal_name": "Sharma Distributors LLP",
        "state_id": "27",
        "pan": "AAKFS1234A",
        "address_line1": "14 Laxmi Road",
        "city": "Pune",
        "pincode": "411030",
        "email": "accounts@sharma.example.com",
        "phone": "02024451234",
        "color": "#2f5bea",
    },
    {
        "slug": "patel",
        "name": "Patel Traders",
        "legal_name": "Patel Traders Private Limited",
        "state_id": "24",
        "pan": "AAKCP5678B",
        "address_line1": "Relief Road",
        "city": "Ahmedabad",
        "pincode": "380001",
        "email": "office@patel.example.com",
        "phone": "07925501234",
        "color": "#0f766e",
    },
]


def _gstin(state: str, pan: str) -> str:
    first14 = f"{state}{pan}1Z"
    return first14 + gstin_check_char(first14)


class Command(BaseCommand):
    help = "Load demo data for local development (idempotent)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--admin-email", default="admin@platform.local")
        parser.add_argument("--admin-password", default="admin-dev-password")
        parser.add_argument("--staff-password", default="staff-dev-password")
        parser.add_argument(
            "--reset-admin-2fa",
            action="store_true",
            help="Put the dev super admin back on the fixed dev 2FA key (clears recovery codes).",
        )

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("seed only runs with DEBUG=True")
        email = options["admin_email"]
        admin = User.objects.filter(email=email).first()
        if admin is None:
            User.objects.create_superuser(
                email, options["admin_password"], full_name="Platform Admin"
            )
            self.stdout.write(f"created super admin {email}")
            admin = User.objects.get(email=email)
        elif admin.platform_role_id is None:  # created before platform roles existed
            admin.platform_role = Role.objects.get(tenant__isnull=True, code=PLATFORM_ADMIN_ROLE)
            admin.save(update_fields=["platform_role"])
        if not admin.totp_enabled or options["reset_admin_2fa"]:
            admin.totp_secret, admin.totp_enabled = DEV_TOTP_SECRET, True
            admin.totp_last_step = None
            admin.save(update_fields=["totp_secret", "totp_enabled", "totp_last_step"])
            admin.recovery_codes.all().delete()
            self.stdout.write(f"super admin 2FA key (dev only): {DEV_TOTP_SECRET}")

        beta = Plan.objects.get(is_default=True)
        for demo in DEMO_TENANTS:
            data = {k: v for k, v in demo.items() if k not in ("slug", "color")}
            data["gstin"] = _gstin(demo["state_id"], demo["pan"])
            data["status"] = Tenant.Status.ACTIVE
            tenant, created = Tenant.objects.update_or_create(slug=demo["slug"], defaults=data)
            with tenant_context(tenant.id):
                TenantProfile.objects.get_or_create(tenant=tenant)
                TenantBranding.objects.update_or_create(
                    tenant=tenant,
                    defaults={"display_name": demo["name"], "primary_color": demo["color"]},
                )
                if not Subscription.objects.filter(is_current=True).exists():
                    Subscription.objects.create(tenant=tenant, plan=beta, starts_at=timezone.now())
                self._staff(tenant, options["staff_password"])
                for shop in [*DEMO_SHOPS[tenant.slug], SHARED_SHOP]:
                    self._shop(*shop)
            self.stdout.write(f"{'created' if created else 'updated'} tenant {tenant.slug}")
        self.stdout.write(self.style.SUCCESS("seed complete"))

    def _staff(self, tenant: Tenant, password: str) -> None:
        """<role>@<slug>.example.com for every tenant system role, e.g. owner@sharma.example.com."""
        for code in STAFF_ROLES:
            email = f"{code.lower()}@{tenant.slug}.example.com"
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(
                    email,
                    password,
                    user_type=User.UserType.STAFF,
                    full_name=f"{code.title()} ({tenant.name})",
                )
            role = Role.objects.get(tenant__isnull=True, code=code, is_platform=False)
            Membership.objects.get_or_create(user=user, defaults={"role": role})

    def _shop(self, shop_name: str, contact_name: str, phone: str) -> None:
        if not Retailer.objects.filter(phone=f"+91{phone}").exists():
            create_retailer(shop_name=shop_name, phone=phone, contact_name=contact_name)
