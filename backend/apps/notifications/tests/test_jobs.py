"""Quiet hours and the daily jobs (ADR-048 items 9 to 12): non-urgent messages wait for quiet hours
to end (in-app and urgent ones never do); payment reminders on the configured days, once a day,
paused and resumed by staff; handover reminders per salesman and the handed-over message; the
GST rate-change warning 7 days ahead."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from typing import Any

import pytest
from django.utils import timezone

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.billing.tests.helpers import ship_invoice
from apps.catalog.models import ProductTaxRate
from apps.inventory.tests.helpers import make_product
from apps.notifications import delivery, jobs, quiet
from apps.notifications.models import Notification
from apps.orders.tests.helpers import add_stock, make_shop, shop_user
from apps.payments import services as payments
from apps.payments.services import PaymentInput
from apps.platform import selectors
from apps.platform.models import FeatureFlag, TenantFeature
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.errors import InvalidFields
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
S = Notification.Status


def ist(hour: int, minute: int = 0, day: int = 1) -> datetime:
    """A moment in IST, as UTC."""
    return datetime(2026, 10, day, hour, minute, tzinfo=quiet.IST).astimezone(UTC)


@pytest.mark.parametrize(
    ("now", "start", "end", "release"),
    [
        (ist(22, 30), "21:00", "08:00", ist(8, 0, day=2)),
        (ist(7, 59), "21:00", "08:00", ist(8, 0)),
        (ist(21, 0), "21:00", "08:00", ist(8, 0, day=2)),
        (ist(8, 0), "21:00", "08:00", None),
        (ist(12, 0), "21:00", "08:00", None),
        (ist(13, 30), "13:00", "14:00", ist(14, 0)),
        (ist(14, 0), "13:00", "14:00", None),
        (ist(3, 0), "09:00", "09:00", None),  # equal: no quiet hours
    ],
)
def test_quiet_hours(now, start, end, release):
    assert quiet.held_until(now, start, end) == release


@pytest.fixture(autouse=True)
def _daytime(monkeypatch):
    """Tests run at any hour: no quiet hours unless a test sets them."""
    monkeypatch.setattr(quiet, "current_hold", lambda now: None)


@pytest.fixture
def world(tenant_a, django_capture_on_commit_callbacks):
    owner = make_staff_in(tenant_a, "OWNER")
    sales = make_staff_in(tenant_a, "SALES")
    shop = make_shop(tenant_a, email="shop@example.com")
    with tenant_context(tenant_a.pk):
        Retailer.objects.filter(pk=shop.pk).update(whatsapp_opt_in=True, salesperson=sales)
        TenantFeature.objects.create(flag=FeatureFlag.objects.get(code="whatsapp"), enabled=True)
    selectors.invalidate_tenant_features(tenant_a.pk)
    product = make_product(tenant_a, "P-1")
    add_stock(tenant_a, product, "100")
    return {
        "t": tenant_a,
        "owner": owner,
        "sales": sales,
        "shop": shop,
        "login": shop_user(shop),
        "product": product,
        "run": lambda: django_capture_on_commit_callbacks(execute=True),
    }


def rows(world: dict[str, Any], code: str, **filters: Any) -> list[Notification]:
    with tenant_context(world["t"].pk):
        return list(Notification.objects.filter(event_code=code, **filters).order_by("created_at"))


def remind(world: dict[str, Any], on: Any) -> int:
    with world["run"](), tenant_context(world["t"].pk):
        return jobs.payment_reminders(on)


def test_non_urgent_messages_wait_for_quiet_hours_to_end(world, monkeypatch):
    later = timezone.now() + timedelta(hours=3)
    monkeypatch.setattr(quiet, "current_hold", lambda now: later)
    with world["run"]():
        bill = ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "2"))
    assert {n.status for n in rows(world, "invoice.issued")} == {S.SENT}  # urgent: never held
    assert remind(world, bill.due_date - timedelta(days=2)) == 1
    found = {n.channel: n for n in rows(world, "payment.reminder", recipient=world["login"])}
    assert found["IN_APP"].status == S.SENT and found["IN_APP"].send_after is None
    assert (found["WHATSAPP"].status, found["WHATSAPP"].send_after) == (S.PENDING, later)
    with tenant_context(world["t"].pk):
        assert found["WHATSAPP"].pk not in delivery.due()
        Notification.objects.filter(pk=found["WHATSAPP"].pk).update(
            send_after=timezone.now() - timedelta(seconds=1)
        )
        assert found["WHATSAPP"].pk in delivery.due()  # quiet hours ended


def test_payment_reminders_follow_the_configured_days(world):
    with world["run"]():
        bill = ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "2"))
    with tenant_context(world["t"].pk):
        Retailer.objects.filter(pk=world["shop"].pk).update(payment_terms_days=90)
    with world["run"]():  # due much later: not in the reminders about the first bill
        ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "1"))
    due = bill.due_date
    reminded = {
        offset: remind(world, due + timedelta(days=offset))
        for offset in (-3, -2, 0, 3, 4, 7, 15, 30, 44, 45, 60)
    }
    assert reminded == {-3: 0, -2: 1, 0: 0, 3: 1, 4: 0, 7: 1, 15: 1, 30: 1, 44: 0, 45: 1, 60: 1}
    first, overdue = rows(world, "payment.reminder", recipient=world["login"], channel="IN_APP")[:2]
    total = f"₹{bill.grand_total}"
    assert first.body.startswith(f"1 bill to pay, {total} in all (due on ")
    assert f"{total} overdue since " in overdue.body
    assert remind(world, due + timedelta(days=3)) == 1  # the same day again: nothing new
    assert len(rows(world, "payment.reminder", recipient=world["login"], channel="IN_APP")) == 7
    sales_rows = rows(world, "payment.reminder", recipient=world["sales"])
    assert {n.channel for n in sales_rows} == {"IN_APP"}
    whatsapp = rows(world, "payment.reminder", channel="WHATSAPP")[0]
    assert whatsapp.data["compulsory"] is True


def test_paid_bills_are_not_reminded(world):
    with world["run"]():
        bill = ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "2"))
    with world["run"](), tenant_context(world["t"].pk):
        payments.record_payment(
            PaymentInput(world["shop"].pk, bill.grand_total, "CASH", today_ist()),
            by=world["owner"],
        )
    assert remind(world, bill.due_date + timedelta(days=3)) == 0


def test_reminders_can_be_paused_and_resumed(world):
    with world["run"]():
        bill = ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "2"))
    with tenant_context(world["t"].pk):
        with pytest.raises(InvalidFields):
            jobs.pause_reminders(world["shop"].pk, reason=" ", until=None, by=world["owner"])
        with pytest.raises(InvalidFields):
            jobs.pause_reminders(
                world["shop"].pk,
                reason="Disputed bill",
                until=today_ist() - timedelta(days=1),
                by=world["owner"],
            )
        jobs.pause_reminders(
            world["shop"].pk, reason="Disputed bill", until=None, by=world["owner"]
        )
        assert AuditLog.objects.filter(action="notifications.reminders_paused").exists()
    remind(world, bill.due_date + timedelta(days=3))
    paused = rows(world, "payment.reminder")
    assert paused and {(n.status, n.skip_reason) for n in paused} == {(S.SKIPPED, "PAUSED")}
    with tenant_context(world["t"].pk):
        assert jobs.resume_reminders(world["shop"].pk, by=world["owner"])
        assert not jobs.resume_reminders(world["shop"].pk, by=world["owner"])
    remind(world, bill.due_date + timedelta(days=7))
    latest = rows(world, "payment.reminder", recipient=world["login"], channel="WHATSAPP")[-1]
    assert latest.status == S.SENT


def test_a_pause_until_a_date_ends_by_itself(world):
    with world["run"]():
        bill = ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "2"))
    with tenant_context(world["t"].pk):
        jobs.pause_reminders(
            world["shop"].pk, reason="Promised to pay", until=today_ist(), by=world["owner"]
        )
        assert jobs.active_pause(world["shop"].pk, today_ist()) is not None
        assert jobs.active_pause(world["shop"].pk, today_ist() + timedelta(days=1)) is None
    assert bill.due_date + timedelta(days=3) > today_ist()  # 30-day terms
    remind(world, bill.due_date + timedelta(days=3))
    [sent] = rows(world, "payment.reminder", recipient=world["login"], channel="WHATSAPP")
    assert sent.status == S.SENT


def test_handover_reminders_and_the_handed_over_message(world):
    with world["run"](), tenant_context(world["t"].pk):
        collected = payments.collect_payment(
            PaymentInput(world["shop"].pk, D("500.00"), "CASH", today_ist()), by=world["sales"]
        )
    with world["run"](), tenant_context(world["t"].pk):
        assert jobs.handover_reminders(today_ist() + timedelta(days=1)) == 0  # not yet 2 days
        assert jobs.handover_reminders(today_ist() + timedelta(days=2)) == 1
    found = rows(world, "handover.reminder")
    assert {(n.recipient_id, n.channel) for n in found} == {
        (world["sales"].pk, "IN_APP"),
        (world["sales"].pk, "WHATSAPP"),
        (world["owner"].pk, "IN_APP"),  # payments.record
    }
    office = next(n for n in found if n.recipient_id == world["owner"].pk)
    assert "1 collections (₹500.00)" in office.body
    assert office.data["path"] == "/manage/payments/handover"
    with world["run"](), tenant_context(world["t"].pk):
        payments.hand_over([collected.pk], by=world["owner"])
    [told] = rows(world, "payment.handed_over")
    assert (told.recipient_id, told.channel) == (world["sales"].pk, "IN_APP")
    assert collected.number in told.body
    with world["run"](), tenant_context(world["t"].pk):
        assert jobs.handover_reminders(today_ist() + timedelta(days=3)) == 0


def test_gst_rate_changes_are_announced_seven_days_ahead(world):
    today = today_ist()
    other = make_product(world["t"], "P-2")
    first_ever = make_product(world["t"], "P-3")
    with tenant_context(world["t"].pk):
        ProductTaxRate.objects.create(
            product=world["product"], gst_rate=D("12"), effective_from=today + timedelta(days=7)
        )
        ProductTaxRate.objects.create(  # the same rate: not a change
            product=other, gst_rate=D("5"), effective_from=today + timedelta(days=7)
        )
        ProductTaxRate.objects.create(  # cancelled
            product=first_ever,
            gst_rate=D("18"),
            effective_from=today + timedelta(days=7),
            cancelled_at=timezone.now(),
        )
        changes = jobs.upcoming_rate_changes(today)
    assert [(c.code, c.old_rate, c.new_rate) for c in changes] == [("P-1", D("5"), D("12"))]
    with world["run"](), tenant_context(world["t"].pk):
        assert jobs.rate_change_warnings(today + timedelta(days=1)) == 0  # 6 days ahead
        assert jobs.rate_change_warnings(today) == 1
        assert jobs.rate_change_warnings(today) == 1  # again: nothing new
    found = rows(world, "tax.rate_change_upcoming")
    assert {(n.recipient_id, n.channel) for n in found} == {
        (world["owner"].pk, "IN_APP"),
        (world["owner"].pk, "EMAIL"),
    }
    assert "Product P-1 (5% → 12%)" in found[0].body
