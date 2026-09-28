"""Opening balances import (PLAN task 5.5, ADR-046): one row per shop, owed or paid in advance,
once per shop; each row becomes the shop's opening balance."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.dataio.tests.helpers import _client, commit, messages, upload, xlsx
from apps.ledger.models import LedgerAdjustment, RetailerAccount
from apps.ledger.tests.helpers import check_ledger
from apps.orders.tests.helpers import make_shop
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
HEADER = ["Shop", "Amount owed", "As of date", "Note"]


def _file(*rows):
    return xlsx([HEADER, *rows], name="balances.xlsx")


def _balance(tenant, shop):
    with tenant_context(tenant.pk):
        return RetailerAccount.objects.get(retailer=shop).balance


def test_owed_and_advance_balances(tenant_a, owner, run):
    ganesh = make_shop(tenant_a, "9876500061")
    laxmi = make_shop(tenant_a, "9876500062")
    job = upload(
        owner,
        run,
        _file(["9876500061", "12500.00", "31-03-2026", "Old books"], [laxmi.code, "-800", "", ""]),
        kind="OPENING_BALANCES",
    )
    assert job["status"] == "VALIDATED" and job["counts"]["new"] == 2
    job = commit(owner, run, job)
    assert job["counts"]["applied"] == 2
    assert (_balance(tenant_a, ganesh), _balance(tenant_a, laxmi)) == (D("12500.00"), D("-800.00"))
    with tenant_context(tenant_a.pk):
        owed = LedgerAdjustment.objects.get(retailer=ganesh)
        assert (owed.kind, owed.adjustment_date, owed.narration) == (
            "OPENING_DEBIT",
            date(2026, 3, 31),
            "Old books",
        )
        assert LedgerAdjustment.objects.get(retailer=laxmi).kind == "OPENING_CREDIT"
    check_ledger(tenant_a)


def test_problems_are_reported_per_row(tenant_a, owner, run):
    make_shop(tenant_a, "9876500061")
    job = upload(
        owner,
        run,
        _file(
            ["9876500061", "100", "", ""],
            ["9876500061", "50", "", ""],
            ["9999999999", "10", "", ""],
            ["9876500061", "ten", "", ""],
            ["9876500061", "5", "01-01-2099", ""],
        ),
        kind="OPENING_BALANCES",
    )
    found = messages(job)
    assert any("also in row 2" in m for m in found)
    assert any("No shop has" in m for m in found)
    assert any("rupees and paise" in m for m in found)
    assert any("future" in m for m in found)


def test_a_shop_gets_one_opening_balance(tenant_a, owner, run):
    make_shop(tenant_a, "9876500061")
    commit(
        owner,
        run,
        upload(owner, run, _file(["9876500061", "100", "", ""]), kind="OPENING_BALANCES"),
    )
    job = upload(owner, run, _file(["9876500061", "100", "", ""]), kind="OPENING_BALANCES")
    assert any("already has an opening balance" in m for m in messages(job))


def test_needs_ledger_adjust(tenant_a, run):
    make_shop(tenant_a, "9876500061")
    sales = _client(tenant_a, "SALES")
    response = sales.post(
        "/api/v1/imports/",
        {"kind": "OPENING_BALANCES", "mode": "ADD_ONLY", "file": _file(["9876500061", "1"])},
        format="multipart",
    )
    assert response.status_code == 403
