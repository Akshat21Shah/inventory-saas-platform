"""Import jobs (ADR-035): upload → background validation (nothing saved) → report and change
preview → the distributor commits → valid rows applied in the background. Also templates and
exports. Kinds (products, retailers) plug in through ``KINDS``."""

import io
import uuid
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from apps.accounts.models import User
from apps.audit import services as audit
from apps.dataio.kinds.base import Column, Kind, RowPlan
from apps.dataio.kinds.products import ProductsKind
from apps.dataio.kinds.retailers import RetailersKind
from apps.dataio.models import ImportJob
from apps.dataio.parsing import FileProblem, read_sheet, synonyms_for
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields, NotFound
from common.storage import get_storage
from common.tenancy import require_tenant_id, tenant_transaction

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

KINDS: dict[str, Kind] = {"PRODUCTS": ProductsKind(), "RETAILERS": RetailersKind()}
PREVIEW_LIMIT = 1000  # rows of errors / changes kept on the job (the report has all of them)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ImportNotReady(DomainError):
    status_code = 409
    code = ErrorCode.INVALID_STATE_TRANSITION
    default_message = "This import can't be confirmed in its current state."


def kind_for(code: str) -> Kind:
    kind = KINDS.get(code)
    if kind is None:
        raise NotFound()
    return kind


def register(kind: Kind) -> None:
    KINDS[kind.code] = kind


# --- Upload and validation ----------------------------------------------------------------------


@transaction.atomic
def create_job(kind_code: str, mode: str, upload: "UploadedFile[bytes]", *, by: User) -> ImportJob:
    if mode not in ImportJob.Mode.values:
        raise InvalidFields({"mode": ["Choose “Add new only” or “Add new and update existing”."]})
    kind_for(kind_code)
    data = upload.read(10 * 1024 * 1024 + 1)
    name = (upload.name or "import").split("/")[-1][:200]
    job = ImportJob(kind=kind_code, mode=mode, file_name=name, created_by=by)
    job.file_key = f"tenants/{require_tenant_id()}/imports/{job.pk}/{uuid.uuid4().hex}-upload"
    get_storage().put(job.file_key, data, "application/octet-stream")
    job.save()
    audit.record(
        "import.uploaded", target=job, target_repr=name, metadata={"kind": kind_code, "mode": mode}
    )
    job_id, tenant = str(job.pk), str(require_tenant_id())
    from apps.dataio.tasks import validate_import

    transaction.on_commit(lambda: validate_import.delay(job_id=job_id, tenant_id=tenant))
    return job


def _plan(job: ImportJob) -> tuple[Kind, list[RowPlan], list[str]]:
    kind = kind_for(job.kind)
    sheet = read_sheet(job.file_name, get_storage().get(job.file_key), _synonyms(kind))
    notes = [f"Column “{name}” isn't used and was skipped." for name in sheet.ignored]
    required = [c for c in kind.columns if c.required]
    missing = [
        c.label
        for c in required
        if c.name not in sheet.columns and (job.mode == "ADD_ONLY" or c.name == _key(kind))
    ]
    if missing:
        raise FileProblem(
            "The file is missing these columns: "
            + ", ".join(missing)
            + ". Download the template to see the expected columns."
        )
    by = job.committed_by or job.created_by
    assert by is not None
    return kind, kind.plan(sheet, job.mode, by), notes


def _key(kind: Kind) -> str:
    return next(c.name for c in kind.columns if c.label == kind.key_label)


def _synonyms(kind: Kind) -> dict[str, str]:
    return synonyms_for((c.name, (c.label, *c.spellings)) for c in kind.columns)


def validate_job(job_id: str) -> None:
    """Runs in a task with the tenant set but no transaction (file reading is not held in one)."""
    tenant_id = require_tenant_id()
    with tenant_transaction(tenant_id):
        job = ImportJob.objects.select_related("created_by").filter(pk=job_id).first()
        if job is None or job.status != ImportJob.Status.VALIDATING:
            return
    try:
        with tenant_transaction(tenant_id):
            kind, plans, notes = _plan(job)
    except FileProblem as problem:
        with tenant_transaction(tenant_id):
            ImportJob.objects.filter(pk=job_id).update(
                status=ImportJob.Status.FAILED,
                problem=str(problem),
                validated_at=timezone.now(),
            )
        return
    counts = {
        "total": len(plans),
        "new": sum(p.action == "NEW" for p in plans),
        "update": sum(p.action == "UPDATE" for p in plans),
        "unchanged": sum(p.action == "UNCHANGED" for p in plans),
        "error": sum(p.action == "ERROR" for p in plans),
    }
    counts["changes"] = counts["new"] + counts["update"]
    report_key = f"tenants/{tenant_id}/imports/{job_id}/report.xlsx"
    get_storage().put(report_key, build_report(kind, plans), XLSX)
    with tenant_transaction(tenant_id):
        ImportJob.objects.filter(pk=job_id).update(
            status=ImportJob.Status.VALIDATED,
            counts=counts,
            notes=notes,
            report_key=report_key,
            validated_at=timezone.now(),
            errors=[
                {"row": p.number, "key": p.key, "messages": p.messages()}
                for p in plans
                if p.action == "ERROR"
            ][:PREVIEW_LIMIT],
            changes=[
                {
                    "row": p.number,
                    "key": p.key,
                    "action": p.action,
                    "changes": p.changes,
                    "highlight": p.highlight,
                    "warnings": p.warnings,
                }
                for p in plans
                if p.action in ("NEW", "UPDATE")
            ][:PREVIEW_LIMIT],
        )


# --- Commit -------------------------------------------------------------------------------------


@transaction.atomic
def request_commit(job_id: UUID, *, by: User) -> ImportJob:
    job: ImportJob | None = ImportJob.objects.select_for_update().filter(pk=job_id).first()
    if job is None:
        raise NotFound()
    if job.status != ImportJob.Status.VALIDATED:
        raise ImportNotReady()
    if not job.counts.get("changes"):
        raise ImportNotReady("There's nothing to import: every row has an error or no change.")
    job.status, job.committed_by = ImportJob.Status.COMMITTING, by
    job.save(update_fields=["status", "committed_by", "updated_at"])
    audit.record(
        "import.confirmed",
        target=job,
        target_repr=job.file_name,
        metadata={"kind": job.kind, "mode": job.mode, "counts": job.counts},
    )
    job_id_s, tenant = str(job.pk), str(require_tenant_id())
    from apps.dataio.tasks import commit_import

    transaction.on_commit(lambda: commit_import.delay(job_id=job_id_s, tenant_id=tenant))
    return job


def commit_job(job_id: str) -> None:
    """Re-reads and re-checks the file (data may have changed since validation), then applies
    each valid row in its own transaction through the normal services (audited)."""
    tenant_id = require_tenant_id()
    with tenant_transaction(tenant_id):
        job = ImportJob.objects.select_related("committed_by").filter(pk=job_id).first()
        if job is None or job.status != ImportJob.Status.COMMITTING:
            return
        by = job.committed_by
        kind, plans, _notes = _plan(job)
    assert by is not None
    applied, failed = 0, []
    cache: dict[str, Any] = {}
    for plan in plans:
        if plan.action not in ("NEW", "UPDATE"):
            continue
        try:
            with tenant_transaction(tenant_id):
                kind.apply(plan, by=by, cache=cache)
            applied += 1
        except DomainError as exc:  # the data changed since validation; skip the row
            cache.clear()  # created brands/categories may have rolled back with the row
            fields = exc.details.get("fields", {})
            messages = [f"{k}: {' '.join(v)}" for k, v in fields.items()] or [exc.message]
            failed.append({"row": plan.number, "key": plan.key, "messages": messages})
    with tenant_transaction(tenant_id):
        job = ImportJob.objects.get(pk=job_id)
        job.counts = {**job.counts, "applied": applied, "failed": len(failed)}
        job.errors = (failed + job.errors)[:PREVIEW_LIMIT] if failed else job.errors
        job.status, job.committed_at = ImportJob.Status.COMMITTED, timezone.now()
        job.save(update_fields=["counts", "errors", "status", "committed_at", "updated_at"])
        audit.record(
            "import.committed",
            target=job,
            target_repr=job.file_name,
            metadata={"kind": job.kind, "applied": applied, "failed": len(failed)},
        )


def mark_failed(job_id: str, message: str) -> None:
    with tenant_transaction(require_tenant_id()):
        ImportJob.objects.filter(pk=job_id).exclude(status=ImportJob.Status.COMMITTED).update(
            status=ImportJob.Status.FAILED, problem=message
        )


# --- Spreadsheets out: report, template, export -------------------------------------------------

HEADER = Font(bold=True)
ERROR_FILL = PatternFill("solid", fgColor="FDE2E1")
CHANGE_FILL = PatternFill("solid", fgColor="FFF4CE")
STATUS = {"NEW": "New", "UPDATE": "Update", "UNCHANGED": "No change", "ERROR": "Error"}


def _book(rows: Iterable[list[Any]], widths: list[int] | None = None) -> tuple[Workbook, Any]:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    for cell in sheet[1]:
        cell.font = HEADER
    sheet.freeze_panes = "A2"
    for index, width in enumerate(widths or [], start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    return book, sheet


def spreadsheet(rows: Iterable[list[Any]], widths: list[int] | None = None) -> bytes:
    """A one-sheet .xlsx with a bold header row (reports and exports)."""
    book, _sheet = _book(rows, widths)
    return _bytes(book)


def _bytes(book: Workbook) -> bytes:
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def build_report(kind: Kind, plans: list[RowPlan]) -> bytes:
    """Every row with its status and, for errors, exactly what to fix."""
    rows: list[list[Any]] = [["Row", kind.key_label, "Status", "What to fix", "Changes", "Notes"]]
    for plan in plans:
        rows.append(
            [
                plan.number,
                plan.key,
                STATUS[plan.action],
                "\n".join(f"{label}: {message}" for label, message in plan.problems),
                "\n".join(
                    f"{k}: {old or '(blank)'} → {new}" for k, (old, new) in plan.changes.items()
                ),
                "\n".join(plan.warnings),
            ]
        )
    book, sheet = _book(rows, [8, 18, 12, 70, 50, 50])
    for index, plan in enumerate(plans, start=2):
        fill = ERROR_FILL if plan.action == "ERROR" else CHANGE_FILL if plan.highlight else None
        if fill is not None:
            for cell in sheet[index]:
                cell.fill = fill
    return _bytes(book)


def visible_columns(kind: Kind, by: User) -> tuple[Column, ...]:
    """The kind's columns without those the user may not see (ADR-039: cost price)."""
    return tuple(
        c
        for c in kind.columns
        if c.name not in kind.restricted or by.has_permission_code(kind.restricted[c.name])
    )


def build_template(kind: Kind, by: User) -> bytes:
    columns: tuple[Column, ...] = visible_columns(kind, by)
    header = [f"{c.label} *" if c.required else c.label for c in columns]
    book, sheet = _book(
        [header, [c.example for c in columns]], [max(14, len(h) + 4) for h in header]
    )
    sheet.title = kind.label
    guide = book.create_sheet("How to fill")
    guide.append(["Column", "Needed for new rows", "What to enter", "Example"])
    for c in columns:
        guide.append([c.label, "Yes" if c.required else "", c.help, c.example])
    guide.append([])
    guide.append(
        ["* = needed when adding a new row. When updating, a blank cell means “no change”."]
    )
    for title, values in kind.reference_lists().items():
        guide.append([])
        guide.append([title, ", ".join(values)])
    for cell in guide[1]:
        cell.font = HEADER
    guide.column_dimensions["A"].width = 24
    guide.column_dimensions["C"].width = 80
    return _bytes(book)


def build_export(kind: Kind, fmt: str, by: User) -> tuple[bytes, str]:
    columns = visible_columns(kind, by)
    rows = [[c.label for c in columns]] + [
        [row.get(c.name, "") for c in columns] for row in kind.export_rows()
    ]
    if fmt == "csv":
        import csv

        buffer = io.StringIO()
        csv.writer(buffer).writerows(rows)
        return buffer.getvalue().encode("utf-8-sig"), "text/csv"  # BOM: Excel opens it as UTF-8
    book, _sheet = _book(rows, [max(14, len(c.label) + 4) for c in columns])
    return _bytes(book), XLSX
