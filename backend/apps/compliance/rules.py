"""The e-invoicing rules the code depends on (ADR-049 items 2, 3, 5), in one place.

None of these is taken as fact: the thresholds, the reporting limit and the cancellation window
are platform settings holding our current understanding, listed on the pre-production checklist
(PROGRESS items 10-13) until a CA confirms them.
TODO(verify): e-invoicing applicability, which documents need an IRN, the reporting limit and the
cancellation window (PROGRESS pre-production items 10-13; CA questions 23-26).
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID

from apps.billing.models import CreditNote, Invoice
from apps.platform.selectors import get_platform_setting, get_setting, is_feature_enabled

BANDS = ("BELOW_5_CR", "FROM_5_TO_10_CR", "FROM_10_CR")
# The lower bound of each band, in crore.
BAND_FROM = {"BELOW_5_CR": 0, "FROM_5_TO_10_CR": 5, "FROM_10_CR": 10}


@dataclass(frozen=True)
class Turnover:
    band: str
    einvoice_suggested: bool
    reporting_limit_applies: bool
    reporting_days: int


def turnover(tenant_id: UUID, band: str | None = None) -> Turnover:
    """What the declared turnover band (or ``band``, just set) means: suggestions and warnings
    only."""
    band = band or str(get_setting("compliance.turnover_band", tenant_id))
    lower = BAND_FROM.get(band, 0)
    return Turnover(
        band=band,
        einvoice_suggested=lower >= int(get_platform_setting("platform.einvoice_threshold_crore")),
        reporting_limit_applies=lower
        >= int(get_platform_setting("platform.irn_limit_threshold_crore")),
        reporting_days=int(get_platform_setting("platform.irn_reporting_days")),
    )


def report_by(tenant_id: UUID, document_date: date) -> date | None:
    """The last day to obtain the IRN, when the reporting limit applies to the business."""
    t = turnover(tenant_id)
    return document_date + timedelta(days=t.reporting_days) if t.reporting_limit_applies else None


def cancel_window_ends(generated_at: datetime) -> datetime:
    return generated_at + timedelta(
        hours=int(get_platform_setting("platform.irn_cancel_window_hours"))
    )


def einvoicing_on(tenant_id: UUID) -> bool:
    return is_feature_enabled("einvoice", tenant_id)


def needs_irn(document: Invoice | CreditNote) -> bool:
    """B2B invoices (the shop has a GSTIN) and their credit notes; never B2C (ADR-049 item 5).
    The module must be on; credentials are checked when the document is sent."""
    return einvoicing_on(document.tenant_id) and bool(document.buyer.get("gstin"))
