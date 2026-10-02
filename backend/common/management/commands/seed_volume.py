"""Speed-check data (ADR-050 item 13): three test distributors with 40,000, 5,000 and 5,000 orders
over a year (``common.demo_volume``), checked with ``reconcile()`` before it commits, then their
suppliers, purchase orders and reorder suggestions (``common.demo_purchasing``, ADR-053), and
free-goods schemes with the shop activity (``common.demo_growth``, ADR-056), return requests
(``common.demo_selfservice``, ADR-057), and for vol-a the AI module with a month of use
(``common.demo_ai``, ADR-058).

Refuses to run unless DEBUG is on. A distributor that already has orders is left alone. Staff sign
in as owner@vol-a.example.com (and manager@, warehouse@, accounts@, sales1@ …) with the demo staff
password.
"""

import time
from dataclasses import replace
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.platform.models import Tenant
from common.demo_ai import seed_volume_ai
from common.demo_growth import seed_volume_growth
from common.demo_purchasing import seed_purchasing
from common.demo_selfservice import seed_volume_returns
from common.demo_volume import TENANTS, reconcile, seed_tenant
from common.tenancy import tenant_context


class Command(BaseCommand):
    help = "Load 3 test distributors with 40,000 / 5,000 / 5,000 orders over a year (DEBUG only)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--only", choices=[t.slug for t in TENANTS])
        parser.add_argument("--days", type=int, default=365)
        parser.add_argument(
            "--scale",
            type=float,
            default=1.0,
            help="Multiply the orders, shops and products (e.g. 0.1 for a quick try).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("seed_volume only runs with DEBUG=True")
        scale = options["scale"]
        for spec in TENANTS:
            if options["only"] and spec.slug != options["only"]:
                continue
            if scale != 1:
                spec = replace(
                    spec,
                    orders=max(1, round(spec.orders * scale)),
                    shops=max(5, round(spec.shops * scale)),
                    products=max(20, round(spec.products * scale)),
                )
            started = time.monotonic()
            with transaction.atomic():
                result = seed_tenant(spec, days=options["days"], progress=self.stdout.write)
                if result is None:
                    self.stdout.write(f"{spec.slug} already has orders: left alone")
                else:
                    with tenant_context(Tenant.objects.get(slug=spec.slug).pk):
                        problems = reconcile()
                    if problems:  # raising rolls the distributor back
                        raise CommandError(
                            f"{spec.slug} does not reconcile: " + "; ".join(problems)
                        )
                    self.stdout.write(
                        f"{spec.slug}: {result.orders} orders, {result.invoices} invoices, "
                        f"{result.credit_notes} credit notes, {result.payments} payments, "
                        f"{result.ledger_entries} ledger entries, "
                        f"{result.movements} stock movements; "
                        f"reconciled in {time.monotonic() - started:.0f} s"
                    )
            self._purchasing(spec.slug)
            self._growth(spec.slug)
            self._returns(spec.slug)
            if spec.slug == "vol-a":
                self._ai(spec.slug)
        self.stdout.write(self.style.SUCCESS("seed_volume complete"))

    def _purchasing(self, slug: str) -> None:
        """Purchasing and stock planning (ADR-053), also for a distributor seeded before."""
        started = time.monotonic()
        with transaction.atomic():
            added = seed_purchasing(Tenant.objects.get(slug=slug))
        if added is None:
            self.stdout.write(f"{slug} already has suppliers: purchasing left alone")
            return
        self.stdout.write(
            f"{slug}: {added.suppliers} suppliers, {added.links} product links, "
            f"{added.orders} purchase orders ({added.order_lines} lines), "
            f"{added.receipts_linked} receipts linked, {added.suggestions} reorder suggestions "
            f"in {time.monotonic() - started:.0f} s"
        )

    def _growth(self, slug: str) -> None:
        """Free-goods schemes and shop activity (ADR-056), also for a distributor seeded before."""
        started = time.monotonic()
        with transaction.atomic():
            added = seed_volume_growth(Tenant.objects.get(slug=slug))
        if added is None:
            self.stdout.write(f"{slug} already has free-goods schemes: left alone")
            return
        self.stdout.write(
            f"{slug}: {added.schemes} free-goods schemes, activity for {added.shops} shops "
            f"in {time.monotonic() - started:.0f} s"
        )

    def _returns(self, slug: str) -> None:
        """Return requests (ADR-057), also for a distributor seeded before."""
        with transaction.atomic():
            added = seed_volume_returns(Tenant.objects.get(slug=slug))
        if added is None:
            self.stdout.write(f"{slug} already has return requests: left alone")
            return
        self.stdout.write(f"{slug}: {added} return requests")

    def _ai(self, slug: str) -> None:
        """The AI module, product meanings and a month of AI use (ADR-058)."""
        started = time.monotonic()
        with transaction.atomic():
            added = seed_volume_ai(Tenant.objects.get(slug=slug))
        if added is None:
            self.stdout.write(f"{slug} already has AI use: left alone")
            return
        self.stdout.write(
            f"{slug}: AI on, {added:,} searches' use in {time.monotonic() - started:.0f} s"
        )
