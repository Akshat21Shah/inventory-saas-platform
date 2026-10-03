"""Document numbers (spec 5.10, ADR-011, ADR-046 item 1): ``INV/26-27/000001``.

Per tenant, per document type, per financial year (April to March, IST); gapless because the
number is taken under the series row lock inside the issuing transaction and rolls back with it.
The series row is the last lock taken (level L6, PLAN §5.1). At most 16 characters.
"""

from datetime import date

from django.db import connection, transaction
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.audit import services as audit
from apps.billing.models import DocumentSeries, DocumentType
from apps.billing.tax import financial_year, fy_short
from apps.platform.selectors import get_platform_setting
from common.errors import InvalidFields
from common.ids import uuid7
from common.tenancy import require_tenant_id

MAX_LENGTH = 16
PREFIX_PATTERN = r"[A-Z0-9]{1,3}"
DEFAULT_PREFIXES = {
    DocumentType.INVOICE: None,  # ⚙ platform.default_invoice_prefix ("INV")
    DocumentType.CREDIT_NOTE: "CN",
    DocumentType.RECEIPT: "RCT",
    DocumentType.REFUND: "RFD",
}


def default_prefix(document_type: str) -> str:
    """The prefix a new series starts with: the latest series of the type (a prefix the
    distributor chose carries over to the next year), else the default."""
    latest = (
        DocumentSeries.objects.filter(document_type=document_type)
        .order_by("-fy")
        .values_list("prefix", flat=True)
        .first()
    )
    if latest:
        return str(latest)
    fixed = DEFAULT_PREFIXES[DocumentType(document_type)]
    return fixed or str(get_platform_setting("platform.default_invoice_prefix"))


def _ensure_series(document_type: str, fy: str) -> None:
    table = DocumentSeries._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {table} "  # noqa: S608
            "(id, tenant_id, document_type, fy, prefix, padding, next_number, "
            "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, 6, 1, now(), now()) "
            "ON CONFLICT (tenant_id, document_type, fy) DO NOTHING",
            [uuid7(), require_tenant_id(), document_type, fy, default_prefix(document_type)],
        )


def format_number(prefix: str, fy: str, number: int, padding: int = 6) -> str:
    formatted = f"{prefix}/{fy_short(fy)}/{number:0{padding}d}"
    if len(formatted) > MAX_LENGTH:
        raise ValueError(f"document number {formatted} is longer than {MAX_LENGTH} characters")
    return formatted


def next_number(document_type: str, day: date) -> tuple[DocumentSeries, str]:
    """The next number for a document dated ``day`` (IST). Must run inside the transaction that
    saves the document, after every other lock."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("next_number() must run inside the issuing transaction")
    fy = financial_year(day)
    _ensure_series(document_type, fy)
    series: DocumentSeries = DocumentSeries.objects.select_for_update().get(
        document_type=document_type, fy=fy
    )
    number = format_number(series.prefix, fy, series.next_number, series.padding)
    series.next_number += 1
    series.save(update_fields=["next_number", "updated_at"])
    return series, number


@transaction.atomic
def set_prefix(document_type: str, prefix: str, *, day: date, by: User) -> DocumentSeries:
    """Change a series' prefix from the next number of the current financial year (and for later
    years). Numbers already issued keep theirs. Audited."""
    import re

    prefix = prefix.strip().upper()
    if not re.fullmatch(PREFIX_PATTERN, prefix):
        raise InvalidFields({"prefix": [_("Use 1 to 3 capital letters or digits.")]})
    fy = financial_year(day)
    _ensure_series(document_type, fy)
    series: DocumentSeries = DocumentSeries.objects.select_for_update().get(
        document_type=document_type, fy=fy
    )
    before = series.prefix
    if before != prefix:
        series.prefix = prefix
        series.save(update_fields=["prefix", "updated_at"])
        audit.record(
            "billing.series_prefix_changed",
            target=series,
            target_repr=f"{document_type} {fy}",
            changes=audit.diff({"prefix": before}, {"prefix": prefix}),
        )
    return series


def overview(day: date) -> list[dict[str, object]]:
    """Each series for the financial year of ``day``: its prefix and the next number it will
    give (nothing is created or reserved)."""
    fy = financial_year(day)
    current = {s.document_type: s for s in DocumentSeries.objects.filter(fy=fy)}
    rows: list[dict[str, object]] = []
    for document_type in DocumentType:
        series = current.get(document_type.value)
        prefix = series.prefix if series else default_prefix(document_type.value)
        number = series.next_number if series else 1
        rows.append(
            {
                "document_type": document_type.value,
                "prefix": prefix,
                "fy": fy,
                "next_number": format_number(prefix, fy, number, series.padding if series else 6),
                "issued": number - 1,
            }
        )
    return rows
