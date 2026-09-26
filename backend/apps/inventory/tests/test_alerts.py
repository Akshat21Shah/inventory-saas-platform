"""Stock alerts (PLAN §5.4): the right type opens, fires once, resolves, and writes outbox events
only when a row is actually opened or resolved."""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import connection, transaction

from apps.catalog.models import Product
from apps.inventory import alerts, services
from apps.inventory.models import StockAlert, StockLevel
from apps.inventory.services import Ref
from apps.inventory.tests.helpers import make_product
from common.models import OutboxEvent
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
D = Decimal


def _change(tenant, product, action, qty):
    with tenant_context(tenant.pk), transaction.atomic():
        level = services.lock_levels([product.pk], services.default_warehouse())[product.pk]
        action(level, D(qty), Ref("ADJUSTMENT", uuid4()), by=None)


def _alerts(tenant, **filters):
    with tenant_context(tenant.pk):
        return list(StockAlert.objects.filter(**filters).order_by("opened_at"))


def _events(tenant, event_type):
    return OutboxEvent.objects.filter(tenant_id=tenant.pk, event_type=event_type).count()


@pytest.mark.parametrize(
    ("on_hand", "reserved", "backordered", "reorder", "expected"),
    [
        ("0", "0", "0", "5", {"OUT_OF_STOCK"}),
        ("3", "3", "0", "5", {"OUT_OF_STOCK"}),  # all reserved: nothing available
        ("1", "0", "0", "5", {"LOW_STOCK"}),
        ("5", "0", "0", "5", {"LOW_STOCK"}),  # at the reorder level
        ("6", "0", "0", "5", set()),
        ("1", "0", "0", "0", set()),  # no reorder level: never low
        ("0", "0", "4", "0", {"OUT_OF_STOCK", "BACKORDER_DEMAND"}),
        ("9", "0", "1", "5", {"BACKORDER_DEMAND"}),
    ],
)
def test_wanted_types(on_hand, reserved, backordered, reorder, expected):
    level = StockLevel(
        quantity_on_hand=D(on_hand),
        quantity_reserved=D(reserved),
        quantity_backordered=D(backordered),
    )
    assert set(alerts.wanted(level, D(reorder))) == expected


def test_low_stock_fires_once_then_resolves_and_can_fire_again(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant, reorder_level=D("5"))
    _change(tenant, product, services.add, "20")
    # The first stock change from zero resolves OUT_OF_STOCK, which was never opened: no events.
    assert _alerts(tenant) == []
    for _ in range(3):  # 17, 14, 11: still above the reorder level
        _change(tenant, product, services.remove, "3")
    assert _alerts(tenant) == []
    for _ in range(3):  # 8, then 5 (low: at the reorder level), then 2 (still low): one alert
        _change(tenant, product, services.remove, "3")
    open_alerts = _alerts(tenant, status="OPEN")
    assert [a.alert_type for a in open_alerts] == ["LOW_STOCK"]
    assert open_alerts[0].value_at_open == D("5")
    assert _events(tenant, alerts.OPENED) == 1
    _change(tenant, product, services.add, "10")  # 12: resolved
    assert _alerts(tenant, status="OPEN") == []
    assert _events(tenant, alerts.RESOLVED) == 1
    _change(tenant, product, services.remove, "8")  # 4: a new alert
    assert len(_alerts(tenant, alert_type="LOW_STOCK")) == 2
    assert _events(tenant, alerts.OPENED) == 2


def test_out_of_stock_replaces_low_stock(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant, reorder_level=D("5"))
    _change(tenant, product, services.add, "3")
    assert [a.alert_type for a in _alerts(tenant, status="OPEN")] == ["LOW_STOCK"]
    _change(tenant, product, services.reserve, "3")
    assert [a.alert_type for a in _alerts(tenant, status="OPEN")] == ["OUT_OF_STOCK"]
    resolved = _alerts(tenant, status="RESOLVED")
    assert [a.alert_type for a in resolved] == ["LOW_STOCK"] and resolved[0].resolved_at


def test_backorder_demand(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant)
    with tenant_context(tenant.pk), transaction.atomic():
        level = services.lock_levels([product.pk], services.default_warehouse())[product.pk]
        level.quantity_backordered = D("4")  # Phase 4's order services keep this in step
        level.save()
        alerts.evaluate(level)
    types = {a.alert_type for a in _alerts(tenant, status="OPEN")}
    assert types == {"OUT_OF_STOCK", "BACKORDER_DEMAND"}


def test_reorder_level_change_is_re_evaluated(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant)
    _change(tenant, product, services.add, "4")
    assert _alerts(tenant) == []
    with tenant_context(tenant.pk), transaction.atomic():
        Product.objects.filter(pk=product.pk).update(reorder_level=D("10"))
        services.refresh_alerts([product.pk])
    assert [a.alert_type for a in _alerts(tenant, status="OPEN")] == ["LOW_STOCK"]


def test_alerts_are_rolled_back_with_the_change(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant, reorder_level=D("5"))
    _change(tenant, product, services.add, "10")
    with pytest.raises(RuntimeError), tenant_context(tenant.pk), transaction.atomic():
        level = services.lock_levels([product.pk], services.default_warehouse())[product.pk]
        services.remove(level, D("8"), Ref("ADJUSTMENT", uuid4()), by=None)
        raise RuntimeError("the business transaction fails later")
    assert _alerts(tenant) == [] and _events(tenant, alerts.OPENED) == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.concurrency
def test_concurrent_evaluations_open_one_alert(make_tenant):
    """Twenty transactions evaluate the same low level without the stock lock: still one alert."""
    import threading

    tenant = make_tenant()
    product = make_product(tenant, reorder_level=D("5"))
    with tenant_context(tenant.pk), transaction.atomic():
        StockLevel.objects.filter(product=product).update(quantity_on_hand=D("2"))
    barrier = threading.Barrier(20)
    errors = []

    def work():
        try:
            with tenant_context(tenant.pk), transaction.atomic():
                level = StockLevel.objects.get(product=product)
                barrier.wait()
                alerts.evaluate(level)
        except BaseException as exc:
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=work) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(_alerts(tenant, status="OPEN")) == 1
    assert _events(tenant, alerts.OPENED) == 1
