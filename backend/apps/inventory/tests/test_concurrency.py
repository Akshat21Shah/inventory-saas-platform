"""Real concurrency (PLAN §5.5): threads, each with its own database connection and transaction,
released together by a barrier. Stock never goes negative and is never reserved twice."""

import os
import random
import threading
import time
from collections import Counter
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from django.db import connection, transaction

from apps.inventory import services
from apps.inventory.models import StockLevel
from apps.inventory.services import InsufficientStock, Ref, StockReserved
from apps.inventory.tests.helpers import check_invariants, make_product
from common.db import retry_on_deadlock
from common.tenancy import tenant_context

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.concurrency]
D = Decimal
EXPECTED = (InsufficientStock, StockReserved)


def _parallel(count: int, work: Callable[[int], Any]) -> tuple[list[Any], list[BaseException]]:
    barrier = threading.Barrier(count)
    results: list[Any] = []
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            barrier.wait()
            results.append(work(index))
        except BaseException as exc:  # collected and asserted on by the test
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results, errors


def _ref() -> Ref:
    return Ref("ORDER", uuid4())


def _stock(tenant, product, qty: str) -> None:
    with tenant_context(tenant.pk), transaction.atomic():
        level = services.lock_levels([product.pk], services.default_warehouse())[product.pk]
        services.add(level, D(qty), _ref(), by=None)


def _level(tenant, product) -> StockLevel:
    with tenant_context(tenant.pk):
        level: StockLevel = StockLevel.objects.get(product=product)
        return level


def test_last_unit_is_reserved_once(make_tenant):
    """test_last_unit_race: 20 shops try to reserve the last unit at the same moment."""
    tenant = make_tenant()
    product = make_product(tenant)
    _stock(tenant, product, "1")

    def reserve_one(_: int) -> str:
        with tenant_context(tenant.pk), transaction.atomic():
            level = services.lock_levels([product.pk], services.default_warehouse())[product.pk]
            services.reserve(level, D("1"), _ref(), by=None)
        return "reserved"

    results, errors = _parallel(20, reserve_one)
    assert results == ["reserved"]
    assert len(errors) == 19 and all(isinstance(e, InsufficientStock) for e in errors)
    level = _level(tenant, product)
    assert (level.quantity_on_hand, level.quantity_reserved) == (1, 1)
    check_invariants(tenant)


def test_concurrent_removals_never_go_negative(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant)
    _stock(tenant, product, "5")

    def remove_one(_: int) -> str:
        with tenant_context(tenant.pk), transaction.atomic():
            level = services.lock_levels([product.pk], services.default_warehouse())[product.pk]
            services.remove(level, D("1"), _ref(), by=None)
        return "removed"

    results, errors = _parallel(20, remove_one)
    assert len(results) == 5
    assert len(errors) == 15 and all(isinstance(e, InsufficientStock) for e in errors)
    assert _level(tenant, product).quantity_on_hand == 0
    check_invariants(tenant)


def test_reserve_and_remove_race_keeps_reservations(make_tenant):
    """Removals racing reservations never take stock that has been reserved (PLAN S4)."""
    tenant = make_tenant()
    product = make_product(tenant)
    _stock(tenant, product, "10")

    def work(index: int) -> str:
        with tenant_context(tenant.pk), transaction.atomic():
            level = services.lock_levels([product.pk], services.default_warehouse())[product.pk]
            if index % 2:
                services.reserve(level, D("1"), _ref(), by=None)
                return "reserve"
            services.remove(level, D("1"), _ref(), by=None)
            return "remove"

    results, errors = _parallel(30, work)
    assert all(isinstance(e, EXPECTED) for e in errors)
    counts = Counter(results)
    level = _level(tenant, product)
    assert level.quantity_reserved == counts["reserve"]
    assert level.quantity_on_hand == 10 - counts["remove"]
    assert counts["reserve"] + counts["remove"] == 10  # every unit went one way or the other
    check_invariants(tenant)


def test_mixed_operations_have_no_deadlocks_and_keep_invariants(make_tenant):
    """test_no_deadlock_mixed_ops: random receipts, removals, reservations and releases across 5
    products, each transaction naming its products in shuffled order."""
    seconds = float(os.environ.get("STOCK_RACE_SECONDS", "30"))
    tenant = make_tenant()
    products = [make_product(tenant, f"MIX-{i}") for i in range(5)]
    for product in products:
        _stock(tenant, product, "20")
    stop_at = time.monotonic() + seconds
    done: Counter[str] = Counter()
    lock = threading.Lock()

    @retry_on_deadlock(attempts=3)
    def one_transaction(rng: random.Random) -> str:
        chosen = rng.sample(products, rng.randint(1, 3))  # shuffled on purpose
        with tenant_context(tenant.pk), transaction.atomic():
            levels = services.lock_levels([p.pk for p in chosen], services.default_warehouse())
            for product in chosen:
                level = levels[product.pk]
                qty = D(rng.randint(1, 4))
                action = rng.choice(["receive", "remove", "reserve", "release"])
                if action == "receive":
                    services.receive(level, qty, _ref(), by=None, unit_cost=D("2.5"))
                elif action == "remove":
                    services.remove(level, qty, _ref(), by=None)
                elif action == "reserve":
                    services.reserve(level, qty, _ref(), by=None)
                elif level.quantity_reserved > 0:
                    services.release(level, min(qty, level.quantity_reserved), _ref(), by=None)
        return "ok"

    def worker(index: int) -> int:
        rng = random.Random(index)
        count = 0
        while time.monotonic() < stop_at:
            try:
                one_transaction(rng)
                outcome = "ok"
            except EXPECTED:
                outcome = "refused"
            with lock:
                done[outcome] += 1
            count += 1
        return count

    results, errors = _parallel(8, worker)
    assert errors == [], errors  # no deadlock got past the retry, no database check fired
    assert sum(results) == done["ok"] + done["refused"] and done["ok"] > 0
    check_invariants(tenant)


def test_a_draft_is_posted_once(make_tenant):
    from apps.accounts.tests.factories import make_staff_in
    from apps.inventory import receipts

    tenant = make_tenant()
    owner = make_staff_in(tenant, "OWNER")
    product = make_product(tenant)
    with tenant_context(tenant.pk):
        draft = receipts.create_draft(
            receipts.ReceiptInput(lines=[receipts.LineInput(product.pk, D("3"))]), by=owner
        )

    def post(_: int) -> str:
        with tenant_context(tenant.pk):
            return str(receipts.post(draft.pk, by=owner).number)

    results, errors = _parallel(10, post)
    assert len(results) == 1
    assert len(errors) == 9 and all(isinstance(e, receipts.NotDraft) for e in errors)
    assert _level(tenant, product).quantity_on_hand == 3
    check_invariants(tenant)


def test_receipt_numbers_have_no_gaps_under_load(make_tenant):
    from apps.accounts.tests.factories import make_staff_in
    from apps.inventory import receipts

    tenant = make_tenant()
    owner = make_staff_in(tenant, "OWNER")
    products = [make_product(tenant, f"N-{i}") for i in range(3)]

    def post(index: int) -> str:
        lines = [receipts.LineInput(p.pk, D("1")) for p in random.sample(products, 2)]
        with tenant_context(tenant.pk):
            receipt = receipts.create_and_post(receipts.ReceiptInput(lines=lines), by=owner)
        return str(receipt.number)

    results, errors = _parallel(10, post)
    assert errors == []
    assert sorted(int(n.rsplit("-", 1)[1]) for n in results) == list(range(1, 11))
    check_invariants(tenant)
