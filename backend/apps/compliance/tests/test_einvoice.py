"""Getting IRNs (ADR-049 items 5, 6 and 8) with the mock GST provider: automatically for B2B
invoices and credit notes, never for B2C or with the module off; the portal down and timeouts
retried, a lost answer recovered, refusals and missing credentials failing at once with staff
told; staff asking with the button; the bill message held for the IRN and released; the PDF
printed again with the IRN and QR code; the reporting-limit date; and the API."""

from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.utils import timezone

from apps.billing import credit_notes, documents
from apps.billing.credit_notes import ReturnLine
from apps.billing.models import Invoice
from apps.compliance import einvoice, tasks
from apps.compliance.adapters.mock import MockGspClient
from apps.compliance.models import EInvoiceRecord, GstCredential
from apps.compliance.tests.conftest import switch_on
from apps.compliance.tests.helpers import bills_sent, credentials, record_of, sell, sweep
from apps.notifications.models import Notification
from apps.orders.tests.helpers import settings
from apps.platform import selectors as platform_selectors
from apps.platform.validators import gstin_check_char
from apps.retailers.models import Retailer
from common.storage import get_storage
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
S = EInvoiceRecord.Status
API = "/api/v1"


def test_a_b2b_invoice_gets_its_irn_and_is_printed_again(world):
    invoice = sell(world)
    rec = record_of(world, invoice)
    assert (rec.status, rec.attempts, rec.document_number_key) == (S.GENERATED, 1, invoice.number)
    assert rec.request_document["buyer"]["gstin"] == world["b2b"].gstin
    assert (invoice.einvoice_status, invoice.irn, invoice.ack_no) == (
        "GENERATED",
        rec.irn,
        rec.ack_no,
    )
    assert invoice.signed_qr.startswith("MOCK.")
    with tenant_context(world["t"].pk):
        printed = get_storage().get(Invoice.objects.get(pk=invoice.pk).pdf_key).decode()
    assert rec.irn in printed and 'alt="e-invoice QR code"' in printed
    assert "data:image/svg+xml" in printed


def test_b2c_bills_and_a_switched_off_module_get_no_irn(world):
    local = sell(world, "b2c")
    assert local.einvoice_status == "NOT_APPLICABLE"
    with tenant_context(world["t"].pk):
        assert not EInvoiceRecord.objects.filter(invoice=local).exists()
        context = documents.invoice_context(local, documents.COPIES[:1])
    assert "qr" not in context
    from apps.platform.models import FeatureFlag, TenantFeature

    with tenant_context(world["t"].pk):
        TenantFeature.objects.filter(flag=FeatureFlag.objects.get(code="einvoice")).update(
            enabled=False
        )
    platform_selectors.invalidate_tenant_features(world["t"].pk)
    off = sell(world)
    assert off.einvoice_status == "NOT_APPLICABLE" and not off.irn


def test_the_portal_down_is_tried_again_until_it_answers(world):
    MockGspClient.script("PORTAL_DOWN", "PORTAL_DOWN")
    invoice = sell(world)
    rec = record_of(world, invoice)
    assert (rec.status, rec.attempts, rec.error_code, rec.retryable) == (
        S.PENDING,
        1,
        "PORTAL_DOWN",
        True,
    )
    assert rec.next_retry_at is not None
    assert timedelta(seconds=50) < rec.next_retry_at - timezone.now() <= timedelta(minutes=1)
    with tenant_context(world["t"].pk):
        assert einvoice.due() == []  # not yet
    sweep(world)
    rec = record_of(world, invoice)
    assert (rec.status, rec.attempts) == (S.PENDING, 2)
    sweep(world)
    assert record_of(world, invoice).status == S.GENERATED


def test_after_the_last_retry_it_fails_and_staff_are_told(world, monkeypatch):
    monkeypatch.setattr(einvoice, "RETRY_MINUTES", (1,))
    MockGspClient.script("TIMEOUT", "TIMEOUT")
    invoice = sell(world)
    sweep(world)
    rec = record_of(world, invoice)
    assert (rec.status, rec.error_code, rec.retryable, rec.attempts) == (
        S.FAILED,
        "TIMEOUT",
        True,
        2,
    )
    with tenant_context(world["t"].pk):
        told = {
            n.channel: n
            for n in Notification.objects.filter(
                event_code="einvoice.failed", recipient=world["owner"]
            )
        }
        assert Invoice.objects.get(pk=invoice.pk).einvoice_status == "FAILED"
    assert set(told) == {"IN_APP", "EMAIL"}
    assert told["IN_APP"].title == f"IRN failed: {invoice.number}"
    assert told["IN_APP"].data["path"] == f"/manage/invoices/{invoice.pk}"
    # Staff try again: a fresh round.
    with world["run"]():
        retried = world["staff"].post(f"{API}/invoices/{invoice.pk}/einvoice/")
    assert retried.status_code == 200
    assert record_of(world, invoice).status == S.GENERATED


def test_a_refusal_fails_at_once_with_the_portals_reason(world):
    with tenant_context(world["t"].pk):
        inactive = "29ZZZZZ9999Z1Z"
        Retailer.objects.filter(pk=world["b2b"].pk).update(
            gstin=inactive + gstin_check_char(inactive), pan="ZZZZZ9999Z"
        )
    invoice = sell(world)
    rec = record_of(world, invoice)
    assert (rec.status, rec.error_code, rec.retryable, rec.attempts) == (
        S.FAILED,
        "INVALID_GSTIN",
        False,
        1,
    )
    assert rec.error_message == "The buyer's GSTIN is not active on the portal."


def test_a_lost_answer_is_recovered_from_the_portal(world):
    MockGspClient.script("TIMEOUT_AFTER_SAVE")
    invoice = sell(world)
    assert record_of(world, invoice).error_code == "TIMEOUT"
    sweep(world)
    rec = record_of(world, invoice)
    assert rec.status == S.GENERATED
    assert rec.irn == MockGspClient.irn_of(rec.request_document)


def test_missing_credentials_fail_until_they_work(world):
    credentials(world["t"], GstCredential.Status.FAILED)
    invoice = sell(world)
    rec = record_of(world, invoice)
    assert (rec.status, rec.error_code, rec.attempts) == (S.FAILED, "CREDENTIALS_NOT_READY", 0)
    credentials(world["t"])
    with world["run"]():
        world["staff"].post(f"{API}/invoices/{invoice.pk}/einvoice/")
    assert record_of(world, invoice).status == S.GENERATED


def test_with_automatic_irns_off_staff_press_the_button(world):
    settings(world["t"], einvoice__auto_generate=False)
    invoice = sell(world)
    rec = record_of(world, invoice)
    assert (rec.status, rec.requested_at, rec.attempts) == (S.PENDING, None, 0)
    shown = world["staff"].get(f"{API}/invoices/{invoice.pk}/").json()["einvoice"]
    assert (shown["status"], shown["can_request"]) == ("PENDING", True)
    with tenant_context(world["t"].pk):
        assert einvoice.due() == []  # the sweep leaves it for staff
    with world["run"]():
        pressed = world["staff"].post(f"{API}/invoices/{invoice.pk}/einvoice/")
    assert pressed.json()["status"] == "PENDING"  # the response is before the send commits
    assert record_of(world, invoice).status == S.GENERATED
    from apps.audit.models import AuditLog

    assert AuditLog.objects.filter(action="einvoice.requested").count() == 1


def test_a_credit_note_gets_its_own_irn(world):
    invoice = sell(world, qty="2")
    with world["run"](), tenant_context(world["t"].pk):
        note = credit_notes.issue_return(
            invoice.pk,
            [ReturnLine(invoice.lines.get().pk, D("1"))],
            reason="DAMAGED",
            note="",
            by=world["owner"],
        )
    with tenant_context(world["t"].pk):
        rec = EInvoiceRecord.objects.get(credit_note=note)
        note.refresh_from_db()
    assert (rec.status, rec.document_type) == (S.GENERATED, "CREDIT_NOTE")
    assert rec.request_document["original_invoice"]["number"] == invoice.number
    assert note.irn == rec.irn != record_of(world, invoice).irn
    detail = world["staff"].get(f"{API}/credit-notes/{note.pk}/").json()
    assert (detail["irn"], detail["einvoice"]["status"]) == (rec.irn, "GENERATED")


def test_a_worker_that_died_mid_send_is_picked_up(world):
    MockGspClient.script("PORTAL_DOWN")
    invoice = sell(world)
    with tenant_context(world["t"].pk):
        EInvoiceRecord.objects.filter(invoice=invoice).update(
            status=S.SUBMITTED,
            next_retry_at=None,
            updated_at=timezone.now() - timedelta(minutes=11),
        )
        assert einvoice.due() == [record_of(world, invoice).pk]
    with world["run"]():
        tasks.retry_due_for_tenant.apply(kwargs={"tenant_id": str(world["t"].pk)})
    assert record_of(world, invoice).status == S.GENERATED


def test_the_bill_message_waits_for_the_irn(world):
    MockGspClient.script("PORTAL_DOWN")
    sell(world)
    with tenant_context(world["t"].pk):
        held = {n.channel: n for n in Notification.objects.filter(event_code="invoice.issued")}
    assert held["IN_APP"].status == "SENT"  # in the app at once
    for channel in ("WHATSAPP", "EMAIL"):
        row = held[channel]
        assert (row.status, row.data["held_for_irn"]) == ("PENDING", True)
        assert row.send_after > timezone.now() + timedelta(minutes=9)
    assert bills_sent() == 0
    sweep(world)  # the IRN arrives: the messages go
    with tenant_context(world["t"].pk):
        sent = {
            n.channel: n.status for n in Notification.objects.filter(event_code="invoice.issued")
        }
    assert sent == {"IN_APP": "SENT", "WHATSAPP": "SENT", "EMAIL": "SENT"}
    assert bills_sent() == 1


def test_the_bill_message_goes_after_ten_minutes_anyway(world):
    from apps.notifications import tasks as notification_tasks

    MockGspClient.script(*["PORTAL_DOWN"] * 5)
    sell(world)
    with tenant_context(world["t"].pk):
        Notification.objects.filter(event_code="invoice.issued", status="PENDING").update(
            send_after=timezone.now() - timedelta(seconds=1)
        )
    assert bills_sent() == 0
    with world["run"]():
        notification_tasks.send_due_for_tenant.apply(kwargs={"tenant_id": str(world["t"].pk)})
    assert bills_sent() == 1


def test_the_reporting_limit_shows_for_the_largest_businesses(world):
    settings(world["t"], einvoice__auto_generate=False)
    invoice = sell(world)
    shown = world["staff"].get(f"{API}/invoices/{invoice.pk}/").json()["einvoice"]
    assert shown["report_by"] is None
    settings(world["t"], compliance__turnover_band="FROM_10_CR")
    shown = world["staff"].get(f"{API}/invoices/{invoice.pk}/").json()["einvoice"]
    assert shown["report_by"] == (invoice.invoice_date + timedelta(days=30)).isoformat()
    assert shown["past_report_by"] is False
    counts = world["staff"].get(f"{API}/einvoices/counts/").json()
    assert counts == {"pending": 1, "failed": 0, "near_report_by": 0}


@covers("einvoices", "einvoice", "einvoice-counts", "invoice-einvoice", "credit-note-einvoice")
def test_the_einvoice_api(world):
    MockGspClient.script("PORTAL_DOWN")
    failing = sell(world)
    done = sell(world)
    rows = world["staff"].get(f"{API}/einvoices/").json()["results"]
    assert {r["document_number"]: r["status"] for r in rows} == {
        failing.number: "PENDING",
        done.number: "GENERATED",
    }
    row = next(r for r in rows if r["document_number"] == failing.number)
    assert (row["shop_name"], row["error_code"], row["grand_total"]) == (
        "Kaveri Traders",
        "PORTAL_DOWN",
        f"{failing.grand_total:.2f}",
    )
    only = world["staff"].get(f"{API}/einvoices/?status=GENERATED").json()["results"]
    assert [r["document_number"] for r in only] == [done.number]
    found = world["staff"].get(f"{API}/einvoices/?search={done.number.lower()}").json()
    assert [r["document_number"] for r in found["results"]] == [done.number]
    assert world["staff"].get(f"{API}/einvoices/?status=NOPE").status_code == 400
    detail = world["staff"].get(f"{API}/einvoices/{row['id']}/").json()
    assert detail["document_id"] == str(failing.pk)
    assert world["staff"].get(f"{API}/einvoices/counts/").json()["pending"] == 1

    local = sell(world, "b2c")
    b2c = world["staff"].post(f"{API}/invoices/{local.pk}/einvoice/")
    assert b2c.status_code == 400
    # Roles and other businesses.
    assert world["sales"].get(f"{API}/einvoices/").status_code == 403
    assert world["sales"].post(f"{API}/invoices/{failing.pk}/einvoice/").status_code == 403
    assert world["other"].get(f"{API}/einvoices/").json()["results"] == []
    assert world["other"].get(f"{API}/einvoices/{row['id']}/").status_code == 404
    switch_on(world["tb"], "einvoice")
    assert world["other"].post(f"{API}/invoices/{failing.pk}/einvoice/").status_code == 404
    assert world["other"].post(f"{API}/credit-notes/{failing.pk}/einvoice/").status_code == 404


def test_asking_for_an_irn_needs_the_module(world):
    invoice = sell(world, "b2c")
    no_module = world["other"].post(f"{API}/invoices/{invoice.pk}/einvoice/")
    assert (no_module.status_code, no_module.json()["error"]["code"]) == (
        403,
        "MODULE_NOT_ENABLED",
    )
