"""Demo data loader. PHASE 0 SKELETON: creates the super admin and two demo tenant stubs.

Later phases extend it to the full spec (2 distributors, 20 retailers, 200 products, price lists…).
Refuses to run unless DEBUG is on.
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.accounts.models import User
from apps.platform.models import Tenant

DEMO_TENANTS = [("Sharma Distributors", "sharma"), ("Patel Traders", "patel")]


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
        for name, slug in DEMO_TENANTS:
            _, created = Tenant.objects.get_or_create(
                slug=slug, defaults={"name": name, "status": Tenant.Status.ACTIVE}
            )
            if created:
                self.stdout.write(f"created tenant {slug}")
        self.stdout.write(self.style.SUCCESS("seed complete (Phase 0 skeleton)"))
