"""Database guarantees of billing, ledger and payments (PLAN §2.9-2.12, ADR-011/017/046): issued
documents change only in their running, PDF and e-invoice columns; lines, ledger entries and
allocations are append-only; balances are checked by the database."""

from datetime import date
from decimal import Decimal as D

import pytest
from django.db import IntegrityError, InternalError, ProgrammingError, connection, transaction

from apps.accounts.tests.factories import make_staff_in
from apps.billing.models import (
    CreditNote,
    CreditNoteLine,
    DocumentSeries,
    DocumentType,
    Invoice,
    InvoiceLine,
)
from apps.inventory.tests.helpers import make_product
from apps.ledger.models import Allocation, LedgerAdjustment, LedgerEntry, RetailerAccount
from apps.orders import transitions
from apps.orders.models import Fulfilment, FulfilmentLine
from apps.orders.tests.helpers import add_stock, make_shop, place
from apps.payments.models import Payment
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
GUARDED = (IntegrityError, InternalError, ProgrammingError)


@pytest.fixture
def world(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    product = make_product(tenant_a, "A", base_price=D("100"))
    add_stock(tenant_a, product, "10")
    order = place(tenant_a, shop, (product, "2"))
    with tenant_context(tenant_a.pk):
        transitions.accept_order(order.pk, by=owner)
        shipment = Fulfilment.objects.get(order=order)
        series = DocumentSeries.objects.create(
            document_type=DocumentType.INVOICE, fy="2026-27", prefix="INV"
        )
    return {"t": tenant_a, "shop": shop, "order": order, "shipment": shipment, "series": series}


def _invoice(world, **extra):
    with tenant_context(world["t"].pk):
        invoice = Invoice.objects.create(
            number=extra.pop("number", "INV/26-27/000001"),
            series=world["series"],
            fy="2026-27",
            retailer=world["shop"],
            place_of_supply_id="27",
            supply_type="INTRA",
            invoice_date=date(2026, 9, 28),
            due_date=date(2026, 10, 28),
            order=world["order"],
            fulfilment=world["shipment"],
            issued_trigger="ON_DISPATCH",
            taxable_total=D("200.00"),
            cgst_total=D("5.00"),
            sgst_total=D("5.00"),
            grand_total=D("210.00"),
            balance_due=D("210.00"),
            **extra,
        )
        fl = FulfilmentLine.objects.get(fulfilment=world["shipment"])
        InvoiceLine.objects.create(
            invoice=invoice,
            line_no=1,
            order_line_id=fl.order_line_id,
            fulfilment_line=fl,
            product_id=fl.product_id,
            description="Product A",
            product_code="A",
            hsn_code="1905",
            unit_code="PCS",
            quantity=D("2"),
            unit_price=D("100.00"),
            gross_amount=D("200.00"),
            taxable_value=D("200.00"),
            gst_rate=D("5"),
            cgst_rate=D("2.5"),
            cgst_amount=D("5.00"),
            sgst_rate=D("2.5"),
            sgst_amount=D("5.00"),
            line_total=D("210.00"),
            order_rate=D("5"),
        )
        return invoice


def test_issued_invoice_changes_only_in_running_columns(world):
    invoice = _invoice(world)
    with tenant_context(world["t"].pk):
        Invoice.objects.filter(pk=invoice.pk).update(
            amount_paid=D("10.00"),
            balance_due=D("200.00"),
            payment_status="PARTIAL",
            pdf_status="READY",
            pdf_key="k",
        )
        for change in (
            {"grand_total": D("1")},
            {"number": "X"},
            {"invoice_date": date(2026, 1, 1)},
        ):
            with pytest.raises(GUARDED, match="immutable"), transaction.atomic():
                Invoice.objects.filter(pk=invoice.pk).update(**change)
        table = Invoice._meta.db_table  # the database refuses, not just Django
        with (
            pytest.raises(GUARDED, match="immutable"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(f"DELETE FROM {table} WHERE id = %s", [invoice.pk])  # noqa: S608
        with pytest.raises(GUARDED, match="append-only"), transaction.atomic():
            InvoiceLine.objects.filter(invoice=invoice).update(quantity=D("1"))


def test_invoice_balance_must_add_up(world):
    invoice = _invoice(world)
    with tenant_context(world["t"].pk), pytest.raises(IntegrityError), transaction.atomic():
        Invoice.objects.filter(pk=invoice.pk).update(amount_paid=D("10.00"))  # balance stale
    with pytest.raises(IntegrityError), transaction.atomic():
        _invoice(world, number="INV/26-27/000002", round_off=D("1.00"))


def test_one_invoice_per_shipment_and_unique_numbers(world):
    _invoice(world)
    with pytest.raises(IntegrityError), transaction.atomic():
        _invoice(world, number="INV/26-27/000002")  # same shipment


def test_series_prefix_is_checked(world):
    with tenant_context(world["t"].pk), pytest.raises(IntegrityError), transaction.atomic():
        DocumentSeries.objects.create(
            document_type=DocumentType.CREDIT_NOTE, fy="2026-27", prefix="A-B"
        )


def test_credit_notes_are_guarded_like_invoices(world):
    invoice = _invoice(world)
    with tenant_context(world["t"].pk):
        series = DocumentSeries.objects.create(
            document_type=DocumentType.CREDIT_NOTE, fy="2026-27", prefix="CN"
        )
        note = CreditNote.objects.create(
            number="CN/26-27/000001",
            series=series,
            fy="2026-27",
            retailer=world["shop"],
            place_of_supply_id="27",
            supply_type="INTRA",
            note_date=date(2026, 9, 29),
            invoice=invoice,
            kind="RETURN",
            return_reason="DAMAGED",
            grand_total=D("105.00"),
            applied_to_invoice=D("105.00"),
        )
        CreditNoteLine.objects.create(
            credit_note=note,
            line_no=1,
            invoice_line=invoice.lines.get(),
            quantity=D("1"),
            disposition="RETURN_TO_STOCK",
            taxable_value=D("100.00"),
            cgst_amount=D("2.50"),
            sgst_amount=D("2.50"),
            line_total=D("105.00"),
        )
        with pytest.raises(GUARDED, match="immutable"), transaction.atomic():
            CreditNote.objects.filter(pk=note.pk).update(grand_total=D("1"))
        with pytest.raises(IntegrityError), transaction.atomic():
            CreditNote.objects.create(
                number="CN/26-27/000002",
                series=series,
                fy="2026-27",
                retailer=world["shop"],
                place_of_supply_id="27",
                supply_type="INTRA",
                note_date=date(2026, 9, 29),
                invoice=invoice,
                kind="RETURN",
                grand_total=D("1.00"),  # a return needs a reason
            )


def test_ledger_entries_are_append_only_and_one_sided(world):
    with tenant_context(world["t"].pk):
        account = RetailerAccount.objects.get(retailer=world["shop"])
        entry = LedgerEntry.objects.create(
            account=account,
            retailer=world["shop"],
            entry_type="INVOICE",
            entry_date=date(2026, 9, 28),
            debit=D("210.00"),
            balance_after=D("210.00"),
            reference_type="INVOICE",
            reference_id=world["order"].pk,
        )
        with pytest.raises(GUARDED, match="append-only"), transaction.atomic():
            LedgerEntry.objects.filter(pk=entry.pk).update(debit=D("1"))
        with pytest.raises(IntegrityError), transaction.atomic():
            LedgerEntry.objects.create(
                account=account,
                retailer=world["shop"],
                entry_type="PAYMENT",
                entry_date=date(2026, 9, 28),
                debit=D("1"),
                credit=D("1"),
                balance_after=D("0"),
                reference_type="PAYMENT",
                reference_id=world["shop"].pk,
            )
        with pytest.raises(IntegrityError), transaction.atomic():  # posted twice
            LedgerEntry.objects.create(
                account=account,
                retailer=world["shop"],
                entry_type="INVOICE",
                entry_date=date(2026, 9, 28),
                debit=D("210.00"),
                balance_after=D("420.00"),
                reference_type="INVOICE",
                reference_id=world["order"].pk,
            )
        with pytest.raises(IntegrityError), transaction.atomic():
            RetailerAccount.objects.filter(pk=account.pk).update(balance=D("5"))  # totals disagree


def test_allocations_have_one_source_one_target_and_a_sign(world):
    invoice = _invoice(world)
    with tenant_context(world["t"].pk):
        payment = Payment.objects.create(
            number="RCT/26-27/000001",
            retailer=world["shop"],
            amount=D("100.00"),
            mode="CASH",
            status="RECEIVED",
            payment_date=date(2026, 9, 28),
        )
        adjustment = LedgerAdjustment.objects.create(
            retailer=world["shop"],
            kind="DEBIT",
            amount=D("50.00"),
            adjustment_date=date(2026, 9, 28),
            due_date=date(2026, 9, 28),
            narration="Old dues",
            balance_due=D("50.00"),
        )
        first = Allocation.objects.create(
            payment=payment, invoice=invoice, retailer=world["shop"], amount=D("100.00")
        )
        Allocation.objects.create(
            payment=payment,
            invoice=invoice,
            retailer=world["shop"],
            amount=D("-100.00"),
            reverses=first,
        )
        bad = [
            {"payment": payment, "invoice": invoice, "amount": D("-1")},  # negative, not a reversal
            {"payment": payment, "amount": D("1")},  # no target
            {
                "payment": payment,
                "invoice": invoice,
                "debit_adjustment": adjustment,
                "amount": D("1"),
            },  # two targets
            {"invoice": invoice, "amount": D("1")},  # no source
        ]
        for fields in bad:
            with pytest.raises(IntegrityError), transaction.atomic():
                Allocation.objects.create(retailer=world["shop"], **fields)
        with pytest.raises(GUARDED, match="append-only"), transaction.atomic():
            Allocation.objects.filter(pk=first.pk).update(amount=D("5"))
        with pytest.raises(IntegrityError), transaction.atomic():
            Payment.objects.create(
                number="RCT/26-27/000002",
                retailer=world["shop"],
                amount=D("1"),
                mode="CHEQUE",
                status="RECEIVED",
                payment_date=date(2026, 9, 28),  # a cheque needs its number
            )


def test_documents_are_isolated_by_tenant(world, tenant_b):
    _invoice(world)
    with tenant_context(tenant_b.pk):
        assert not Invoice.objects.exists()
        assert not InvoiceLine.objects.exists()
        assert not DocumentSeries.objects.exists()
