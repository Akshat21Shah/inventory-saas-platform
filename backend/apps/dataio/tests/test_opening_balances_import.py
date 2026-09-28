"""Opening balances import (PLAN task 5.5, ADR-046, ADR-047): old unpaid bills, one row each with
the bill's date and due date (the shop's terms after the bill date if empty), so they age and
fall overdue like invoices; a bill number once per shop; an advance (minus) once per shop."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.dataio.tests.helpers import _client, commit, messages, upload, xlsx
from apps.ledger.models import LedgerAdjustment, RetailerAccount
from apps.ledger.tests.helpers import check_ledger
from apps.orders.tests.helpers import make_shop
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
HEADER = ["Shop", "Amount owed", "Bill number", "Bill date", "Due date", "Note"]


def _file(*rows):
    return xlsx([HEADER, *rows], name="balances.xlsx")


def _balance(tenant, shop):
    with tenant_context(tenant.pk):
        return RetailerAccount.objects.get(retailer=shop).balance


def test_old_bills_and_an_advance(tenant_a, owner, run):
    ganesh = make_shop(tenant_a, "9876500061")
    laxmi = make_shop(tenant_a, "9876500062")
    job = upload(
        owner,
        run,
        _file(
            ["9876500061", "12500.00", "SD/0412", "15-02-2026", "", "Old books"],
            ["9876500061", "3000", "SD/0450", "01-03-2026", "10-03-2026", ""],
            [laxmi.code, "-800", "", "31-03-2026", "", ""],
        ),
        kind="OPENING_BALANCES",
    )
    assert job["status"] == "VALIDATED" and job["counts"]["new"] == 3
    job = commit(owner, run, job)
    assert job["counts"]["applied"] == 3
    assert (_balance(tenant_a, ganesh), _balance(tenant_a, laxmi)) == (D("15500.00"), D("-800.00"))
    with tenant_context(tenant_a.pk):
        first, second = LedgerAdjustment.objects.filter(retailer=ganesh).order_by("adjustment_date")
        assert (first.kind, first.bill_number, first.adjustment_date, first.due_date) == (
            "OPENING_DEBIT",
            "SD/0412",
            date(2026, 2, 15),
            date(2026, 3, 17),  # the shop's 30-day terms
        )
        assert (first.narration, second.due_date) == ("Old books", date(2026, 3, 10))
        assert LedgerAdjustment.objects.get(retailer=laxmi).kind == "OPENING_CREDIT"
    check_ledger(tenant_a)


def test_problems_are_reported_per_row(tenant_a, owner, run):
    make_shop(tenant_a, "9876500061")
    job = upload(
        owner,
        run,
        _file(
            ["9876500061", "100", "B1", "01-03-2026", "", ""],
            ["9876500061", "50", "B1", "02-03-2026", "", ""],
            ["9999999999", "10", "", "01-03-2026", "", ""],
            ["9876500061", "ten", "", "01-03-2026", "", ""],
            ["9876500061", "5", "", "01-01-2099", "", ""],
            ["9876500061", "5", "", "", "", ""],
            ["9876500061", "5", "", "10-03-2026", "01-03-2026", ""],
            ["9876500061", "-5", "", "01-03-2026", "", ""],
            ["9876500061", "-6", "", "01-03-2026", "", ""],
        ),
        kind="OPENING_BALANCES",
    )
    found = messages(job)
    for text in (
        "also in row 2",
        "No shop has",
        "rupees and paise",
        "future",
        "Enter the date",
        "before the bill date",
        "advance is also in row 9",
    ):
        assert any(text in m for m in found), text


def test_a_bill_or_an_advance_is_imported_once(tenant_a, owner, run):
    make_shop(tenant_a, "9876500061")
    rows = (
        ["9876500061", "100", "B1", "01-03-2026", "", ""],
        ["9876500061", "-50", "", "01-03-2026", "", ""],
    )
    commit(owner, run, upload(owner, run, _file(*rows), kind="OPENING_BALANCES"))
    job = upload(owner, run, _file(*rows), kind="OPENING_BALANCES")
    found = messages(job)
    assert any("already in the shop's account" in m for m in found)
    assert any("already has an opening advance" in m for m in found)


def test_needs_ledger_adjust(tenant_a, run):
    make_shop(tenant_a, "9876500061")
    sales = _client(tenant_a, "SALES")
    response = sales.post(
        "/api/v1/imports/",
        {
            "kind": "OPENING_BALANCES",
            "mode": "ADD_ONLY",
            "file": _file(["9876500061", "1", "", "01-03-2026", "", ""]),
        },
        format="multipart",
    )
    assert response.status_code == 403
