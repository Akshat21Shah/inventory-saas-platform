"""Report exports (ADR-050 item 10).

A small export is made in the request and returned as the file. A large one (more rows than
``platform.report_async_rows``), and every report marked ``background_only`` (the GST workbook),
is recorded as a ``ReportRun`` and made on the ``reports`` worker queue: the file goes to private
storage, the requester gets "Report ready" in the app, and the file is deleted when its link
expires (``platform.report_link_days``)."""

from __future__ import annotations

import io
import logging
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, BinaryIO
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.platform.selectors import get_platform_setting
from apps.reports import engine, files
from apps.reports.models import ReportRun
from apps.reports.registry import REGISTRY, Context, FilterKind, Report, Scope
from common import outbox
from common.errors import InvalidFields
from common.storage import get_storage
from common.tenancy import require_tenant_id, tenant_transaction

logger = logging.getLogger(__name__)
F = ReportRun.Format
S = ReportRun.Status
EXTENSION = {F.XLSX: "xlsx", F.PDF: "pdf"}
CONTENT_TYPE = {F.XLSX: files.XLSX, F.PDF: files.PDF}


@dataclass(frozen=True)
class Built:
    data: bytes
    name: str
    content_type: str
    rows: int


def _stored(params: dict[str, Any]) -> dict[str, Any]:
    """Filters as the run keeps them (strings, parsed again when the file is made)."""
    return {k: v.isoformat() if isinstance(v, date) else str(v) for k, v in params.items()}


def _names(entity: str, value: Any) -> str:
    from apps.catalog.models import Brand, Category, Product
    from apps.retailers.models import Retailer

    lookups: dict[str, tuple[Any, str]] = {
        "shop": (Retailer.objects, "shop_name"),
        "product": (Product.objects, "name"),
        "category": (Category.objects, "name"),
        "brand": (Brand.objects, "name"),
        "staff": (User.objects, "full_name"),
    }
    if entity not in lookups:
        return str(value)
    manager, field = lookups[entity]
    return str(manager.filter(pk=value).values_list(field, flat=True).first() or value)


def described(report: Report, params: dict[str, Any]) -> list[tuple[str, str]]:
    out = []
    for f in report.filters:
        if f.key not in params:
            continue
        value = params[f.key]
        if f.kind == FilterKind.DATE:
            text = f"{value:%d-%m-%Y}"
        elif f.kind == FilterKind.BOOL:
            text = "Yes" if value else "No"
        elif f.kind == FilterKind.ID:
            text = _names(f.entity, value)
        else:
            text = str(value)
        out.append((f.label, text))
    return out


def write(report: Report, ctx: Context, fmt: str, by: str, out: BinaryIO) -> tuple[str, int]:
    """Write the file to ``out``; returns its name and how many rows it holds."""
    about = files.about(report, ctx, described(report, ctx.params), by)
    maker = files.pdf if fmt == F.PDF else files.excel
    rows = maker(report, ctx, about, out)
    return files.file_name(report, ctx, EXTENSION[F(fmt)]), rows


def build(report: Report, ctx: Context, fmt: str, by: str) -> Built:
    """A small export, made in the request."""
    out = io.BytesIO()
    name, rows = write(report, ctx, fmt, by, out)
    return Built(out.getvalue(), name, CONTENT_TYPE[F(fmt)], rows)


def _who(user: User) -> str:
    return str(user.full_name or user.email)


def request_export(report: Report, ctx: Context, fmt: str, *, by: User) -> Built | ReportRun:
    """The file at once, or a queued run for the background (see the module docstring)."""
    if fmt not in F.values:
        raise InvalidFields({"format": ["Choose Excel or PDF."]})
    if fmt == F.PDF and not report.pdf:
        raise InvalidFields({"format": ["This report is exported to Excel only."]})
    background = report.background_only or report.sheets is not None
    if not background:
        limit = int(get_platform_setting("platform.report_async_rows"))
        background = engine.count(report.rows(ctx)) > limit
    if not background:
        return build(report, ctx, fmt, _who(by))
    run: ReportRun = ReportRun.objects.create(
        report_code=report.code,
        title=report.title,
        params=_stored(ctx.params),
        format=fmt,
        requested_by=by,
        own_shops=ctx.scope.own_shops,
        costs=ctx.scope.costs,
    )
    tenant_id = require_tenant_id()
    transaction.on_commit(lambda: _enqueue(run.pk, tenant_id))
    return run


def _enqueue(run_id: UUID, tenant_id: UUID) -> None:
    from apps.reports.tasks import build_run

    build_run.delay(run_id=str(run_id), tenant_id=str(tenant_id))


def _finish(run_id: UUID, **changes: Any) -> ReportRun | None:
    run: ReportRun | None = ReportRun.objects.select_for_update().filter(pk=run_id).first()
    if run is None:
        return None
    for field, value in changes.items():
        setattr(run, field, value)
    run.finished_at = timezone.now()
    run.save()
    event = "report.ready" if run.status == S.READY else "report.failed"
    outbox.emit(
        event,
        aggregate_type="report_run",
        aggregate_id=run.pk,
        payload={"run_id": str(run.pk), "requested_by": str(run.requested_by_id)},
    )
    return run


def make_run(run_id: UUID) -> str:
    """The background part (``reports`` queue): no transaction is held while the file goes to
    storage. The requester must still be allowed to open the report."""
    tenant_id = require_tenant_id()
    with tenant_transaction(tenant_id):
        run = ReportRun.objects.select_for_update().filter(pk=run_id).first()
        if run is None or run.status != S.QUEUED:
            return "skipped"
        run.status, run.started_at = S.RUNNING, timezone.now()
        run.save(update_fields=["status", "started_at", "updated_at"])
        user = run.requested_by
    report = REGISTRY.get(run.report_code)
    if report is None or not user.is_active or not engine.may_open(user, report):
        with tenant_transaction(tenant_id):
            _finish(run.pk, status=S.FAILED, error="You can no longer open this report.")
        return "refused"
    try:
        # Rows are read in chunks and the file is written to disk, then uploaded in parts: memory
        # stays flat however large the export (``make perf-exports``).
        with tempfile.TemporaryFile() as out:
            with tenant_transaction(tenant_id):
                ctx = Context(
                    engine.parse(report, run.params), Scope(user.pk, run.own_shops, run.costs)
                )
                name, rows = write(report, ctx, run.format, _who(user), out)
            out.seek(0)
            key = f"tenants/{tenant_id}/reports/{run.pk}/{name}"
            get_storage().put_file(key, out, CONTENT_TYPE[F(run.format)])
    except Exception:
        logger.exception("report export failed", extra={"report": run.report_code})
        with tenant_transaction(tenant_id):
            _finish(run.pk, status=S.FAILED, error="The report could not be made. Try again.")
        return "failed"
    days = int(get_platform_setting("platform.report_link_days"))
    with tenant_transaction(tenant_id):
        _finish(
            run.pk,
            status=S.READY,
            file_key=key,
            file_name=name,
            row_count=rows,
            expires_at=timezone.now() + timedelta(days=days),
        )
    return "ready"


def download_url(run: ReportRun) -> str | None:
    """A fresh 5-minute link while the file lasts."""
    if run.status != S.READY or not run.file_key:
        return None
    if run.expires_at and run.expires_at <= timezone.now():
        return None
    return get_storage().presigned_get(run.file_key, 300)


def expire_due() -> int:
    """Delete files whose link has run out (all tenants; the platform path)."""
    from common.platform_db import platform_db

    alias = platform_db("reports.expire_exports")
    due = list(
        ReportRun.objects.unscoped()
        .using(alias)
        .filter(status=S.READY, expires_at__lte=timezone.now())
        .values_list("pk", "file_key")[:500]
    )
    storage = get_storage()
    for pk, key in due:
        if key:
            try:
                storage.delete(key)
            except Exception:  # a file already gone must not stop the rest
                logger.warning("report file not deleted", extra={"key": key})
        ReportRun.objects.unscoped().using(alias).filter(pk=pk).update(
            status=S.EXPIRED, file_key="", updated_at=timezone.now()
        )
    return len(due)
