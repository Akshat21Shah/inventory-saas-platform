"""The speed check (ADR-050 item 13, PLAN §10.2j item 12): the distributor dashboard and the first
page of every report (with its default filters: this month) for a volume distributor's staff
member, timed through the whole API in-process (middleware, authentication, permissions,
queries, serialisation) as the runtime database role. Prints p50 / p95 / max per page and fails
when a p95 is over the target (300 ms). ``make perf``, after ``make seed-volume``.

Not timed: the web server in front and the network. DEBUG stays on as in development, which
records every query; production is a little faster.
"""

import statistics
import time
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.tokens import issue_tokens
from apps.platform.models import Tenant

API = "/api/v1"


class Command(BaseCommand):
    help = "Time the dashboard and every report's first page against the p95 target."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", default="vol-a")
        parser.add_argument("--user", default="owner", help="owner, manager, sales1, …")
        parser.add_argument("--runs", type=int, default=20)
        parser.add_argument("--target-ms", type=float, default=300.0)

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = Tenant.objects.filter(slug=options["tenant"]).first()
        if tenant is None:
            raise CommandError(f"no distributor {options['tenant']}: run make seed-volume first")
        email = f"{options['user']}@{tenant.slug}.example.com"
        user = User.objects.filter(email=email).first()
        if user is None:
            raise CommandError(f"no staff member {email}")
        host = f"{tenant.slug}.{settings.PLATFORM_DOMAIN}"
        client = APIClient(HTTP_HOST=host, HTTP_X_FORWARDED_HOST=host)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, tenant.pk).access}")
        catalogue = client.get(f"{API}/reports/")
        if catalogue.status_code != 200:
            raise CommandError(f"the report list answered {catalogue.status_code}")
        pages = [("dashboard", f"{API}/dashboard/")] + [
            (r["code"], f"{API}/reports/{r['code']}/") for r in catalogue.json()
        ]
        target, runs = options["target_ms"], options["runs"]
        self.stdout.write(
            f"{tenant.slug} as {email}, {runs} runs each, target p95 < {target:.0f} ms"
        )
        self.stdout.write(f"{'page':<26}{'p50':>8}{'p95':>8}{'max':>8}  rows")
        slow = []
        for name, url in pages:
            first = client.get(url)  # warms caches, as a second visit would
            if first.status_code != 200:
                raise CommandError(f"{name} answered {first.status_code}: {first.content[:300]!r}")
            timings = []
            for _ in range(runs):
                started = time.perf_counter()
                client.get(url)
                timings.append((time.perf_counter() - started) * 1000)
            p50 = statistics.median(timings)
            p95 = statistics.quantiles(timings, n=20, method="inclusive")[-1]
            count = first.json().get("count", "")
            flag = "  SLOW" if p95 > target else ""
            self.stdout.write(
                f"{name:<26}{p50:>8.0f}{p95:>8.0f}{max(timings):>8.0f}  {count}{flag}"
            )
            if p95 > target:
                slow.append(f"{name} ({p95:.0f} ms)")
        if slow:
            raise CommandError("over the target: " + ", ".join(slow))
        self.stdout.write(self.style.SUCCESS(f"every page's p95 is under {target:.0f} ms"))
