"""Document numbers (ADR-011, ADR-046 item 1): gapless per type and financial year, at most 16
characters, the prefix changeable, taken under a lock (race test)."""

import threading
from datetime import date

import pytest
from django.db import connection, transaction

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.billing import numbering
from apps.billing.models import DocumentSeries, DocumentType
from common.errors import InvalidFields
from common.tenancy import tenant_context
from common.testing.isolation import covers

SEPT = date(2026, 9, 28)
MARCH = date(2027, 3, 31)
APRIL = date(2027, 4, 1)


def _next(tenant, doc=DocumentType.INVOICE, day=SEPT):
    with tenant_context(tenant.pk), transaction.atomic():
        return numbering.next_number(doc, day)[1]


@pytest.mark.django_db
class TestNumbers:
    def test_each_type_counts_on_its_own_from_one(self, tenant_a):
        assert _next(tenant_a) == "INV/26-27/000001"
        assert _next(tenant_a) == "INV/26-27/000002"
        assert _next(tenant_a, DocumentType.CREDIT_NOTE) == "CN/26-27/000001"
        assert _next(tenant_a, DocumentType.RECEIPT) == "RCT/26-27/000001"
        assert all(len(_next(tenant_a)) <= 16 for _ in range(3))

    def test_a_new_financial_year_restarts_at_one(self, tenant_a):
        assert _next(tenant_a, day=MARCH) == "INV/26-27/000001"
        assert _next(tenant_a, day=APRIL) == "INV/27-28/000001"
        assert _next(tenant_a, day=MARCH) == "INV/26-27/000002"

    def test_tenants_have_their_own_numbers(self, tenant_a, tenant_b):
        assert _next(tenant_a) == "INV/26-27/000001"
        assert _next(tenant_b) == "INV/26-27/000001"

    def test_a_failed_issue_leaves_no_gap(self, tenant_a):
        with tenant_context(tenant_a.pk), pytest.raises(RuntimeError), transaction.atomic():
            numbering.next_number(DocumentType.INVOICE, SEPT)
            raise RuntimeError("the invoice could not be saved")
        assert _next(tenant_a) == "INV/26-27/000001"

    def test_prefix_change_applies_from_the_next_number_and_the_next_year(self, tenant_a):
        owner = make_staff_in(tenant_a, "OWNER")
        assert _next(tenant_a) == "INV/26-27/000001"
        with tenant_context(tenant_a.pk):
            numbering.set_prefix(DocumentType.INVOICE, "sd", day=SEPT, by=owner)
            assert AuditLog.objects.filter(action="billing.series_prefix_changed").count() == 1
            with pytest.raises(InvalidFields):
                numbering.set_prefix(DocumentType.INVOICE, "SHOP", day=SEPT, by=owner)
            with pytest.raises(InvalidFields):
                numbering.set_prefix(DocumentType.INVOICE, "A-1", day=SEPT, by=owner)
        assert _next(tenant_a) == "SD/26-27/000002"
        assert _next(tenant_a, day=APRIL) == "SD/27-28/000001"

    def test_format_guards_the_length(self):
        assert numbering.format_number("RCT", "2026-27", 999999) == "RCT/26-27/999999"
        with pytest.raises(ValueError):
            numbering.format_number("RCT", "2026-27", 1000000)


@pytest.mark.django_db(transaction=True)
@pytest.mark.concurrency
def test_twelve_documents_at_the_same_moment_get_twelve_numbers_in_a_row(make_tenant):
    tenant = make_tenant()
    barrier = threading.Barrier(12)
    numbers: list[str] = []
    errors: list[BaseException] = []

    def issue() -> None:
        try:
            barrier.wait()
            numbers.append(_next(tenant))
        except BaseException as exc:  # collected and asserted on
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=issue) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert sorted(numbers) == [f"INV/26-27/{n:06d}" for n in range(1, 13)]
    with tenant_context(tenant.pk):
        assert DocumentSeries.objects.get().next_number == 13


@pytest.mark.django_db(transaction=True)
def test_numbers_are_only_taken_inside_the_issuing_transaction(make_tenant):
    tenant = make_tenant()
    with tenant_context(tenant.pk), pytest.raises(RuntimeError):
        numbering.next_number(DocumentType.INVOICE, SEPT)


@pytest.mark.django_db
@covers("document-series")
def test_the_numbering_settings_api(tenant_a, tenant_b):
    """Any staff member sees the series and the next numbers; only settings.manage changes a
    prefix, from the next number (ADR-046 item 1)."""
    from apps.orders.tests.helpers import client_for

    owner = client_for(tenant_a, make_staff_in(tenant_a, "OWNER"))
    sales = client_for(tenant_a, make_staff_in(tenant_a, "SALES"))
    rows = {r["document_type"]: r for r in sales.get("/api/v1/settings/document-series/").json()}
    assert set(rows) == {"INVOICE", "CREDIT_NOTE", "RECEIPT", "REFUND"}
    assert rows["REFUND"]["next_number"].startswith("RFD/") and rows["INVOICE"]["issued"] == 0
    body = {"document_type": "INVOICE", "prefix": "sd"}
    assert sales.patch("/api/v1/settings/document-series/", body, format="json").status_code == 403
    changed = owner.patch("/api/v1/settings/document-series/", body, format="json").json()
    assert next(r for r in changed if r["document_type"] == "INVOICE")["next_number"].startswith(
        "SD/"
    )
    bad = owner.patch(
        "/api/v1/settings/document-series/",
        {"document_type": "INVOICE", "prefix": "S-D"},
        format="json",
    )
    assert bad.status_code == 400
    outsider = client_for(tenant_b, make_staff_in(tenant_b, "OWNER"))
    theirs = {
        r["document_type"]: r for r in outsider.get("/api/v1/settings/document-series/").json()
    }
    assert theirs["INVOICE"]["prefix"] == "INV"  # their own series, untouched
