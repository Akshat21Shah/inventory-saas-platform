"""The daily summary (ADR-056 items 5-6): at the distributor's time, once per person per day, with
yesterday's figures and what needs action, and only what each person's permissions show."""

from datetime import datetime, time, timedelta
from decimal import Decimal as D
from typing import Any

import pytest
from django.core import mail

from apps.accounts.tests.factories import make_staff_in
from apps.inventory.tests.helpers import make_product
from apps.notifications import jobs
from apps.notifications.models import Notification, NotificationRule
from apps.orders.models import Order
from apps.orders.tests.helpers import add_stock, make_shop, place, settings
from common.dates import IST, today_ist
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


def at(hour: int, minute: int = 0, day: Any = None) -> datetime:
    return datetime.combine(day or today_ist(), time(hour, minute), tzinfo=IST)


@pytest.fixture
def world(tenant_a, django_capture_on_commit_callbacks):
    # No quiet hours, so the emails go out whatever the clock says while the tests run.
    settings(
        tenant_a, notifications__quiet_hours_start="00:00", notifications__quiet_hours_end="00:00"
    )
    owner = make_staff_in(tenant_a, "OWNER", email="owner@alpha.example.com")
    warehouse = make_staff_in(tenant_a, "WAREHOUSE", email="store@alpha.example.com")
    product = make_product(tenant_a, "P-1", base_price=D("100"))
    add_stock(tenant_a, product, "100")
    shop = make_shop(tenant_a, "9876500071", shop_name="Ganesh Kirana")
    yesterday = at(11, day=today_ist() - timedelta(days=1))
    with django_capture_on_commit_callbacks(execute=True):
        for _ in range(2):
            order = place(tenant_a, shop, (product, "1"))
            with tenant_context(tenant_a.pk):
                Order.objects.filter(pk=order.pk).update(placed_at=yesterday)
        place(tenant_a, shop, (product, "1"))  # today: a new order to accept
    return {
        "t": tenant_a,
        "owner": owner,
        "warehouse": warehouse,
        "run": lambda: django_capture_on_commit_callbacks(execute=True),
    }


def summaries(world: dict[str, Any], now: datetime) -> int:
    mail.outbox.clear()
    with world["run"](), tenant_context(world["t"].pk):
        return jobs.daily_summaries(now)


def rows(world: dict[str, Any], user: Any) -> dict[str, Notification]:
    with tenant_context(world["t"].pk):
        return {
            n.channel: n
            for n in Notification.objects.filter(event_code="summary.daily", recipient=user)
        }


def test_the_owner_gets_yesterday_and_what_needs_action_once_a_day(world):
    assert summaries(world, at(7, 59)) == 0  # before the distributor's time
    assert summaries(world, at(8, 15)) == 1
    owner = rows(world, world["owner"])
    assert set(owner) == {"IN_APP", "EMAIL"}
    # All three orders still wait to be accepted, yesterday's two included.
    assert owner["IN_APP"].body == (
        "Yesterday: 2 orders received (₹210.00) · billed ₹0.00. "
        "Needs action: 3 new orders to accept."
    )
    [email] = [m for m in mail.outbox if m.to == ["owner@alpha.example.com"]]
    assert "summary for" in email.subject
    assert "- 2 orders received (₹210.00)\n- billed ₹0.00" in email.body
    assert "Needs action now:\n- 3 new orders to accept" in email.body
    # Later runs that day send nothing more.
    assert summaries(world, at(8, 30)) == 0
    assert summaries(world, at(18, 0)) == 0
    assert len(rows(world, world["owner"])) == 2


def test_switched_off_or_a_skipped_sunday_sends_nothing(world):
    settings(world["t"], notifications__daily_summary_enabled=False)
    assert summaries(world, at(9)) == 0
    settings(
        world["t"],
        notifications__daily_summary_enabled=True,
        notifications__daily_summary_skip_sunday=True,
        notifications__daily_summary_time="06:30",
    )
    sunday = today_ist() + timedelta(days=(6 - today_ist().weekday()) % 7)
    assert summaries(world, at(7, day=sunday)) == 0
    monday = sunday + timedelta(days=1)
    assert summaries(world, at(6, 29, day=monday)) == 0
    assert summaries(world, at(6, 30, day=monday)) == 1


def test_each_person_sees_only_what_their_permissions_show(world):
    with tenant_context(world["t"].pk):
        NotificationRule.objects.create(
            event_code="summary.daily",
            recipient="STAFF_PERMISSION",
            permission="orders.fulfil",
            channels=["IN_APP"],
        )
    assert summaries(world, at(8, 0)) == 2
    store = rows(world, world["warehouse"])["IN_APP"].body
    assert "2 orders received" in store  # the warehouse sees orders
    assert "billed" not in store and "collected" not in store and "overdue" not in store
    owner = rows(world, world["owner"])["IN_APP"].body
    assert "2 orders received" in owner
