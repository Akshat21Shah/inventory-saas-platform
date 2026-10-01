"""The export check (ADR-050 item 13; product owner, 2026-10-01): the heaviest background exports
of a volume distributor, each made exactly as the reports worker makes it (``services.make_run``:
rows read in chunks, the file written in openpyxl's streaming mode, then stored), each in a
process of its own so its peak memory is its own. Prints rows, file size, time and memory; fails
over the time or memory limit. ``make perf-exports``, after ``make seed-volume``.

- ``sales_by_invoice``: the sales register for the last 366 days (the longest range allowed).
- ``gst_summary``: the GSTR-1 workbook for the last whole quarter.
- ``stock_movements``: the movement history for the last 92 days (the longest range allowed).
"""

import argparse
import json
import resource
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.accounts.models import User
from apps.platform.models import Tenant
from apps.reports import engine, services
from apps.reports.models import ReportRun
from apps.reports.registry import REGISTRY
from common.dates import today_ist
from common.storage import get_storage
from common.tenancy import tenant_context, tenant_transaction


def _last_quarter(today: date) -> dict[str, str]:
    start = date(today.year, (today.month - 1) // 3 * 3 + 1, 1)
    first = (start - timedelta(days=1)).replace(day=1)
    first = date(first.year, (first.month - 1) // 3 * 3 + 1, 1)
    return {"date_from": first.isoformat(), "date_to": (start - timedelta(days=1)).isoformat()}


def _days(n: int) -> Callable[[date], dict[str, str]]:
    return lambda today: {
        "date_from": (today - timedelta(days=n - 1)).isoformat(),
        "date_to": today.isoformat(),
    }


EXPORTS: dict[str, Callable[[date], dict[str, str]]] = {
    "sales_by_invoice": _days(366),
    "gst_summary": _last_quarter,
    "stock_movements": _days(92),
}


def _rss_mb() -> float:
    """Resident memory now (Linux; the worker's platform), else the peak so far."""
    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    return _peak_mb()


def _peak_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 1024 if sys.platform != "darwin" else peak / 1024 / 1024


class Command(BaseCommand):
    help = "Time the heaviest background exports and their memory (after make seed-volume)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", default="vol-a")
        parser.add_argument("--user", default="owner")
        parser.add_argument("--limit-seconds", type=float, default=120.0)
        parser.add_argument("--limit-mb", type=float, default=250.0, help="memory growth limit")
        parser.add_argument("--one", choices=list(EXPORTS), help=argparse.SUPPRESS)  # a child

    def handle(self, *args: Any, **options: Any) -> None:
        if options["one"]:
            self.stdout.write(json.dumps(self._one(options["one"], options)))
            return
        results = []
        for name in EXPORTS:
            child = subprocess.run(  # noqa: S603 - this command, with fixed arguments
                [
                    sys.executable,
                    "manage.py",
                    "perf_exports",
                    "--one",
                    name,
                    "--tenant",
                    options["tenant"],
                    "--user",
                    options["user"],
                ],
                cwd=settings.BASE_DIR,
                capture_output=True,
                text=True,
                check=False,
            )
            if child.returncode != 0:
                raise CommandError(f"{name} failed:\n{child.stderr[-2000:]}")
            results.append(json.loads(child.stdout.strip().splitlines()[-1]))
        self.stdout.write(
            f"{options['tenant']} as {options['user']}; limits {options['limit_seconds']:.0f} s "
            f"and {options['limit_mb']:.0f} MB of memory growth"
        )
        self.stdout.write(
            f"{'export':<18}{'period':<25}{'rows':>8}{'file MB':>9}{'seconds':>9}"
            f"{'before MB':>11}{'peak MB':>9}{'growth MB':>11}"
        )
        over = []
        for r in results:
            growth = r["peak_mb"] - r["before_mb"]
            self.stdout.write(
                f"{r['export']:<18}{r['period']:<25}{r['rows']:>8}{r['file_mb']:>9.1f}"
                f"{r['seconds']:>9.1f}{r['before_mb']:>11.0f}{r['peak_mb']:>9.0f}{growth:>11.0f}"
            )
            if r["seconds"] > options["limit_seconds"] or growth > options["limit_mb"]:
                over.append(r["export"])
        if over:
            raise CommandError("over a limit: " + ", ".join(over))
        self.stdout.write(self.style.SUCCESS("every export is within its limits"))

    def _one(self, name: str, options: dict[str, Any]) -> dict[str, Any]:
        tenant = Tenant.objects.filter(slug=options["tenant"]).first()
        if tenant is None:
            raise CommandError(f"no distributor {options['tenant']}: run make seed-volume first")
        user = User.objects.get(email=f"{options['user']}@{tenant.slug}.example.com")
        report = REGISTRY[name]
        params = EXPORTS[name](today_ist())
        with tenant_context(tenant.pk):
            with tenant_transaction(tenant.pk):
                scope = engine.scope_for(user, report)
                run = ReportRun.objects.create(
                    report_code=report.code,
                    title=report.title,
                    params=params,
                    format=ReportRun.Format.XLSX,
                    requested_by=user,
                    own_shops=scope.own_shops,
                    costs=scope.costs,
                )
            before = _rss_mb()
            started = time.perf_counter()
            outcome = services.make_run(run.pk)
            seconds = time.perf_counter() - started
            peak = _peak_mb()
            with tenant_transaction(tenant.pk):
                run.refresh_from_db()
                size = len(get_storage().get(run.file_key)) if run.file_key else 0
                if run.file_key:  # a measurement leaves nothing behind
                    get_storage().delete(run.file_key)
                ReportRun.objects.filter(pk=run.pk).delete()
        if outcome != "ready":
            raise CommandError(f"{name}: {outcome} ({run.error})")
        return {
            "export": name,
            "period": f"{params['date_from']} to {params['date_to']}",
            "rows": run.row_count,
            "file_mb": size / 1024 / 1024,
            "seconds": seconds,
            "before_mb": before,
            "peak_mb": peak,
        }
