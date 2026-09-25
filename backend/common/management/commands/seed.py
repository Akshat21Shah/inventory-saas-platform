"""Demo data loader: the super admin and two demo distributors with complete business details.

Phase 1 later switches this to the onboarding service (owner, staff per role, a retailer each);
Phase 2 adds catalog, retailers and pricing. Refuses to run unless DEBUG is on. Idempotent.
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.platform.models import Plan, Subscription, Tenant, TenantBranding, TenantProfile
from apps.platform.validators import gstin_check_char
from common.tenancy import tenant_context

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

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("seed only runs with DEBUG=True")
        email = options["admin_email"]
        if not User.objects.filter(email=email).exists():
            User.objects.create_superuser(
                email, options["admin_password"], full_name="Platform Admin"
            )
            self.stdout.write(f"created super admin {email}")

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
            self.stdout.write(f"{'created' if created else 'updated'} tenant {tenant.slug}")
        self.stdout.write(self.style.SUCCESS("seed complete"))
