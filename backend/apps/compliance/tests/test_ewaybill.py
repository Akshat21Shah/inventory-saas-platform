"""E-way bills (ADR-049 item 8) with the mock GST provider: made at dispatch above the threshold
(between states and within the state), never below it or with the module off; the distance from
the shop address or typed at dispatch; dispatch never waiting (the portal down retried); a
refusal failing with "Try again"; the button when automatic bills are off; a new vehicle
(Part-B); cancelling within the window, and the IRN cancellation waiting for it; the PDF; and
the API."""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.billing import documents
from apps.billing.models import Invoice
from apps.compliance.adapters.mock import MockGspClient
from apps.compliance.models import EWayBill, EWayBillUpdate
from apps.compliance.tests.conftest import switch_on
from apps.compliance.tests.helpers import record_of, sweep
from apps.orders import fulfilment, transitions
from apps.orders.models import Fulfilment
from apps.orders.tests.helpers import place, settings
from apps.retailers.models import RetailerAddress
from common.storage import get_storage
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
S = EWayBill.Status
API = "/api/v1"
VEHICLE = "MH12AB1234"


@pytest.fixture
def ewb_world(world):
    switch_on(world["t"], "ewaybill")
    distance(world, "b2b", 850)
    distance(world, "b2c", 12)
    return world


def distance(world: dict[str, Any], shop: str, km: int | None) -> None:
    with tenant_context(world["t"].pk):
        RetailerAddress.objects.filter(retailer=world[shop]).update(distance_km=km)


def dispatch(
    world: dict[str, Any],
    shop: str = "b2b",
    qty: str = "2",
    *,
    vehicle: str = VEHICLE,
    km: int | None = None,
    by: Any = None,
) -> Invoice:
    """Place, accept, pack and dispatch (the invoice is issued at dispatch)."""
    with world["run"]():
        order = place(world["t"], world[shop], (world["product"], qty))
    with world["run"](), tenant_context(world["t"].pk):
        transitions.accept_order(order.pk, by=world["owner"])
        shipment = Fulfilment.objects.get(order=order)
        fulfilment.pack(shipment.pk, {}, by=world["owner"])
        fulfilment.dispatch(
            shipment.pk,
            fulfilment.Transport(vehicle, "Speedy Roadways", "LR-1", km),
            by=by or world["owner"],
        )
    with tenant_context(world["t"].pk):
        invoice: Invoice = Invoice.objects.get(fulfilment=shipment, status="ISSUED")
        return invoice


def bill_of(world: dict[str, Any], invoice: Invoice) -> EWayBill | None:
    with tenant_context(world["t"].pk):
        found: EWayBill | None = (
            EWayBill.objects.filter(invoice=invoice).order_by("-created_at").first()
        )
        return found


def test_a_big_consignment_gets_its_ewaybill_at_dispatch(ewb_world):
    world = ewb_world
    invoice = dispatch(world)
    ewb = bill_of(world, invoice)
    assert ewb is not None
    assert (ewb.status, ewb.distance_km, ewb.vehicle_number, ewb.transport_doc_no) == (
        S.GENERATED,
        850,
        VEHICLE,
        "LR-1",
    )
    assert len(ewb.ewb_number) == 12 and ewb.consignment_value == invoice.grand_total
    assert ewb.ewb_date is not None
    assert ewb.valid_until == ewb.ewb_date + timedelta(days=5)  # 850 km at 200 a day
    assert ewb.request_document["transport"]["distance_km"] == 850
    assert ewb.request_document["supply"]["category"] == "B2B"
    with tenant_context(world["t"].pk):
        printed = get_storage().get(Invoice.objects.get(pk=invoice.pk).pdf_key).decode()
    assert f"E-way bill no.</b> {ewb.ewb_number}" in printed
    shown = world["staff"].get(f"{API}/invoices/{invoice.pk}/").json()["ewaybill"]
    assert (shown["status"], shown["can_update"], shown["can_cancel"]) == ("GENERATED", True, True)


def test_only_above_the_threshold_for_its_direction(ewb_world):
    world = ewb_world
    small = dispatch(world, qty="1")  # ₹31,500
    assert bill_of(world, small) is None
    local = dispatch(world, "b2c")  # ₹63,000 within the state, no GSTIN
    ewb = bill_of(world, local)
    assert ewb is not None and ewb.request_document["supply"]["category"] == "B2C"
    settings(world["t"], ewaybill__threshold_inter_state="70000.00")
    assert bill_of(world, dispatch(world)) is None
    settings(world["t"], ewaybill__threshold_intra_state="100.00")
    assert bill_of(world, dispatch(world, "b2c", qty="1")) is not None


def test_no_ewaybills_with_the_module_off(world):
    distance(world, "b2b", 850)
    invoice = dispatch(world)
    assert bill_of(world, invoice) is None
    shipment_distance = world["staff"].get(f"{API}/fulfilments/{invoice.fulfilment_id}/").json()
    assert shipment_distance["distance_km"] == 850  # stored for the shipment all the same


def test_dispatch_never_waits_for_the_portal(ewb_world):
    world = ewb_world
    MockGspClient.script("PORTAL_DOWN", "PORTAL_DOWN")  # the IRN takes the first one
    invoice = dispatch(world)
    with tenant_context(world["t"].pk):
        assert Fulfilment.objects.get(pk=invoice.fulfilment_id).status == "DISPATCHED"
    ewb = bill_of(world, invoice)
    assert ewb is not None and (ewb.status, ewb.error_code) == (S.PENDING, "PORTAL_DOWN")
    sweep(world)
    assert bill_of(world, invoice).status == S.GENERATED  # type: ignore[union-attr]


def test_a_missing_distance_fails_and_staff_try_again(ewb_world):
    world = ewb_world
    distance(world, "b2b", None)
    invoice = dispatch(world)
    ewb = bill_of(world, invoice)
    assert ewb is not None
    assert (ewb.status, ewb.error_code, ewb.retryable) == (S.FAILED, "VALIDATION", False)
    assert ewb.error_message == "Enter the distance (1 to 4,000 km)."
    shown = world["staff"].get(f"{API}/invoices/{invoice.pk}/").json()["ewaybill"]
    assert shown["can_request"] is True
    with world["run"]():
        again = world["staff"].post(
            f"{API}/invoices/{invoice.pk}/ewaybill/",
            {"vehicle_number": "mh 12 ab 1234", "distance_km": 850},
            format="json",
        )
    assert again.status_code == 200
    ewb = bill_of(world, invoice)
    assert ewb is not None and (ewb.status, ewb.vehicle_number) == (S.GENERATED, VEHICLE)
    assert AuditLog.objects.filter(action="ewaybill.requested").count() == 1


def test_the_distance_typed_at_dispatch_is_kept_for_the_shop(ewb_world):
    world = ewb_world
    distance(world, "b2b", None)
    first = dispatch(world, km=640)
    assert bill_of(world, first).distance_km == 640  # type: ignore[union-attr]
    with tenant_context(world["t"].pk):
        address = RetailerAddress.objects.get(retailer=world["b2b"])
    assert address.distance_km == 640  # empty before: kept for next time
    second = dispatch(world, km=700)
    assert bill_of(world, second).distance_km == 700  # type: ignore[union-attr]
    with tenant_context(world["t"].pk):
        assert RetailerAddress.objects.get(retailer=world["b2b"]).distance_km == 640


def test_with_automatic_bills_off_staff_press_the_button(ewb_world):
    world = ewb_world
    settings(world["t"], ewaybill__auto_generate=False)
    invoice = dispatch(world)
    ewb = bill_of(world, invoice)
    assert ewb is not None and (ewb.status, ewb.requested_at) == (S.PENDING, None)
    with world["run"]():
        world["staff"].post(
            f"{API}/invoices/{invoice.pk}/ewaybill/",
            {"vehicle_number": VEHICLE, "distance_km": 850},
            format="json",
        )
    assert bill_of(world, invoice).status == S.GENERATED  # type: ignore[union-attr]


@covers("ewaybill-part-b")
def test_a_new_vehicle(ewb_world):
    world = ewb_world
    ewb = bill_of(world, dispatch(world))
    assert ewb is not None
    url = f"{API}/ewaybills/{ewb.pk}/part-b/"
    other = world["staff"].post(
        url, {"vehicle_number": "KA01XY9999", "reason_code": "OTHER"}, format="json"
    )
    assert other.json()["error"]["details"]["fields"] == {"remarks": ["Say why."]}
    with world["run"]():
        changed = world["staff"].post(
            url,
            {
                "vehicle_number": "KA01XY9999",
                "reason_code": "BREAKDOWN",
                "transport_doc_no": "LR-2",
            },
            format="json",
        )
    assert changed.status_code == 200
    ewb = bill_of(world, ewb.invoice)
    assert ewb is not None and (ewb.vehicle_number, ewb.transport_doc_no) == ("KA01XY9999", "LR-2")
    with tenant_context(world["t"].pk):
        [update] = EWayBillUpdate.objects.filter(eway_bill=ewb)
    assert (update.kind, update.status, update.reason_code) == ("PART_B", "DONE", "BREAKDOWN")
    actions = set(AuditLog.objects.values_list("action", flat=True))
    assert {"ewaybill.vehicle_change_requested", "ewaybill.vehicle_changed"} <= actions


@covers("ewaybill-cancel")
def test_cancelling_within_the_window_and_then_the_irn(ewb_world):
    world = ewb_world
    invoice = dispatch(world)
    ewb = bill_of(world, invoice)
    assert ewb is not None
    irn = record_of(world, invoice)
    blocked = world["staff"].post(
        f"{API}/einvoices/{irn.pk}/cancel/", {"reason_code": "DUPLICATE"}, format="json"
    )
    assert blocked.json()["error"]["details"]["fields"]["document"] == [
        f"Cancel e-way bill {ewb.ewb_number} first, then cancel the IRN."
    ]
    shown = world["staff"].get(f"{API}/invoices/{invoice.pk}/").json()["einvoice"]
    assert shown["cancel_blocked"] == {
        "reason": "EWAY_BILL",
        "message": f"Cancel e-way bill {ewb.ewb_number} first, then cancel the IRN.",
        "ewaybill_id": str(ewb.pk),
    }
    MockGspClient.script("PORTAL_DOWN")
    with world["run"]():
        world["staff"].post(
            f"{API}/ewaybills/{ewb.pk}/cancel/", {"reason_code": "ORDER_CANCELLED"}, format="json"
        )
    with tenant_context(world["t"].pk):
        update = EWayBillUpdate.objects.get(eway_bill=ewb)
    assert (update.status, update.error_message) == (
        "PENDING",
        "The e-way bill portal is not available.",
    )
    busy = world["staff"].post(
        f"{API}/ewaybills/{ewb.pk}/cancel/", {"reason_code": "ORDER_CANCELLED"}, format="json"
    )
    assert busy.status_code == 400  # one change at a time
    with tenant_context(world["t"].pk):
        EWayBillUpdate.objects.filter(pk=update.pk).update(
            next_retry_at=timezone.now() - timedelta(minutes=1)
        )
    sweep(world)
    assert bill_of(world, invoice).status == S.CANCELLED  # type: ignore[union-attr]
    with world["run"]():
        cancelled = world["staff"].post(
            f"{API}/einvoices/{irn.pk}/cancel/", {"reason_code": "DUPLICATE"}, format="json"
        )
    assert cancelled.status_code == 200
    assert record_of(world, invoice).status == "CANCELLED"


def test_cancelling_after_the_window_is_refused(ewb_world):
    world = ewb_world
    ewb = bill_of(world, dispatch(world))
    assert ewb is not None
    with tenant_context(world["t"].pk):
        EWayBill.objects.filter(pk=ewb.pk).update(ewb_date=timezone.now() - timedelta(hours=25))
    late = world["staff"].post(
        f"{API}/ewaybills/{ewb.pk}/cancel/", {"reason_code": "DUPLICATE"}, format="json"
    )
    assert late.json()["error"]["details"]["fields"] == {
        "ewaybill": ["The time allowed for cancelling this e-way bill has passed."]
    }


@covers("ewaybills", "ewaybill", "ewaybill-counts", "invoice-ewaybill")
def test_the_ewaybill_api(ewb_world):
    world = ewb_world
    distance(world, "b2b", None)
    failing = dispatch(world)
    distance(world, "b2b", 850)
    done = dispatch(world)
    rows = world["staff"].get(f"{API}/ewaybills/").json()["results"]
    assert {r["invoice_number"]: r["status"] for r in rows} == {
        failing.number: "FAILED",
        done.number: "GENERATED",
    }
    ok = next(r for r in rows if r["invoice_number"] == done.number)
    assert (ok["shop_name"], ok["distance_km"], ok["updates"]) == ("Kaveri Traders", 850, [])
    found = world["staff"].get(f"{API}/ewaybills/?search={ok['ewb_number']}").json()["results"]
    assert [r["id"] for r in found] == [ok["id"]]
    assert world["staff"].get(f"{API}/ewaybills/?status=NOPE").status_code == 400
    assert world["staff"].get(f"{API}/ewaybills/{ok['id']}/").json()["invoice_id"] == str(done.pk)
    assert world["staff"].get(f"{API}/ewaybills/counts/").json() == {"pending": 0, "failed": 1}
    made = world["staff"].post(f"{API}/invoices/{done.pk}/ewaybill/", {}, format="json")
    assert made.json()["error"]["details"]["fields"] == {
        "invoice": ["This invoice already has an e-way bill."]
    }
    # Roles, the module and other businesses.
    assert world["sales"].get(f"{API}/ewaybills/").status_code == 403
    assert world["other"].get(f"{API}/ewaybills/").json()["results"] == []
    assert world["other"].get(f"{API}/ewaybills/{ok['id']}/").status_code == 404
    no_module = world["other"].post(f"{API}/invoices/{done.pk}/ewaybill/", {}, format="json")
    assert no_module.json()["error"]["code"] == "MODULE_NOT_ENABLED"
    switch_on(world["tb"], "ewaybill")
    assert (
        world["other"].post(f"{API}/invoices/{done.pk}/ewaybill/", {}, format="json").status_code
        == 404
    )
    assert (
        world["other"]
        .post(f"{API}/ewaybills/{ok['id']}/cancel/", {"reason_code": "DUPLICATE"}, format="json")
        .status_code
        == 404
    )


def test_the_pdf_has_no_ewaybill_while_there_is_none(ewb_world):
    world = ewb_world
    small = dispatch(world, qty="1")
    with tenant_context(world["t"].pk):
        assert "ewb" not in documents.invoice_context(small, documents.COPIES[:1])


def test_a_failed_ewaybill_tells_staff_and_the_dispatcher_at_once(ewb_world, monkeypatch):
    from apps.accounts.tests.factories import make_staff_in
    from apps.notifications import quiet
    from apps.notifications.models import Notification

    world = ewb_world
    distance(world, "b2b", None)
    packer = make_staff_in(world["t"], "WAREHOUSE")
    monkeypatch.setattr(  # quiet hours now: this message doesn't wait for them
        quiet, "current_hold", lambda now: now + timedelta(hours=8)
    )
    invoice = dispatch(world, by=packer)
    with tenant_context(world["t"].pk):
        shipment = Fulfilment.objects.get(pk=invoice.fulfilment_id)
        rows = list(Notification.objects.filter(event_code="ewaybill.failed"))
    told = {(n.recipient_id, n.channel) for n in rows}
    assert told == {
        (world["owner"].pk, "IN_APP"),
        (world["owner"].pk, "EMAIL"),
        (packer.pk, "IN_APP"),
        (packer.pk, "EMAIL"),
    }
    email = next(n for n in rows if n.channel == "EMAIL")
    assert email.send_after is None and email.status == "SENT"
    assert email.title == f"E-way bill failed: {shipment.number}"
    assert VEHICLE in email.body and "Enter the distance (1 to 4,000 km)." in email.body
    assert email.data["path"] == f"/manage/invoices/{invoice.pk}"


def test_the_dispatcher_recipient_only_while_ewaybills_are_on(ewb_world):
    world = ewb_world
    matrix = world["staff"].get(f"{API}/notification-rules/").json()
    assert "DISPATCHER" in matrix["recipients"]
    failed = next(e for e in matrix["events"] if e["code"] == "ewaybill.failed")
    assert {r["recipient"] for r in failed["rules"]} == {"STAFF_PERMISSION", "DISPATCHER"}
    elsewhere = world["staff"].put(
        f"{API}/notification-rules/order.placed/",
        {"rules": [{"recipient": "DISPATCHER", "channels": ["IN_APP"]}]},
        format="json",
    )
    assert elsewhere.json()["error"]["details"]["fields"]["rules"] == [
        "This recipient is only for failed e-way bills."
    ]
    other = world["other"].get(f"{API}/notification-rules/").json()
    assert "DISPATCHER" not in other["recipients"]
    assert "ewaybill.failed" not in {e["code"] for e in other["events"]}
