import threading
from unittest import mock

import pytest
from django.db import OperationalError, connection, transaction
from psycopg import errors as pg_errors

from common import outbox
from common.db import retry_on_deadlock
from common.models import IdempotencyRecord, OutboxEvent
from common.sequences import next_value
from common.task_base import TenantTask
from common.tenancy import get_current_tenant_id, tenant_context
from common.tests import views
from common.tests.testapp.models import Widget
from config.celery import app as celery_app


# --- idempotency --------------------------------------------------------------------------------
@pytest.mark.django_db
@pytest.mark.urls("common.tests.urls")
class TestIdempotency:
    url = "/test-api/idempotent/"

    def test_requires_key(self, api_client_for, staff_user, tenant_a):
        response = api_client_for(staff_user, tenant_a).post(self.url, {"name": "a"}, format="json")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    def test_rejects_malformed_key(self, api_client_for, staff_user, tenant_a):
        client = api_client_for(staff_user, tenant_a)
        response = client.post(
            self.url, {"name": "a"}, format="json", HTTP_IDEMPOTENCY_KEY="bad key!"
        )
        assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_INVALID"

    def test_duplicate_returns_original_result(self, api_client_for, staff_user, tenant_a):
        client = api_client_for(staff_user, tenant_a)
        first = client.post(
            self.url, {"name": "a"}, format="json", HTTP_IDEMPOTENCY_KEY="key-00000001"
        )
        second = client.post(
            self.url, {"name": "a"}, format="json", HTTP_IDEMPOTENCY_KEY="key-00000001"
        )
        assert first.status_code == second.status_code == 201
        assert first.json() == second.json()
        assert second["Idempotent-Replayed"] == "true"
        assert Widget.objects.unscoped().count() == 1

    def test_same_key_different_body_is_rejected(self, api_client_for, staff_user, tenant_a):
        client = api_client_for(staff_user, tenant_a)
        client.post(self.url, {"name": "a"}, format="json", HTTP_IDEMPOTENCY_KEY="key-00000002")
        response = client.post(
            self.url, {"name": "b"}, format="json", HTTP_IDEMPOTENCY_KEY="key-00000002"
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"

    def test_failed_request_stores_nothing_and_can_be_retried(
        self, api_client_for, staff_user, tenant_a
    ):
        client = api_client_for(staff_user, tenant_a)
        failed = client.post(
            self.url, {"fail": True}, format="json", HTTP_IDEMPOTENCY_KEY="key-00000003"
        )
        assert failed.status_code == 400
        assert not IdempotencyRecord.objects.filter(key="key-00000003").exists()

    def test_keys_are_scoped_per_user(
        self, api_client_for, staff_user, tenant_a, django_user_model
    ):
        other = django_user_model.objects.create_user(
            "other@example.com", "pw-123456789", user_type="STAFF"
        )
        api_client_for(staff_user, tenant_a).post(
            self.url, {"name": "a"}, format="json", HTTP_IDEMPOTENCY_KEY="key-00000004"
        )
        api_client_for(other, tenant_a).post(
            self.url, {"name": "a"}, format="json", HTTP_IDEMPOTENCY_KEY="key-00000004"
        )
        assert Widget.objects.unscoped().count() == 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.urls("common.tests.urls")
@pytest.mark.concurrency
def test_concurrent_duplicates_execute_once(api_client_for, staff_user, tenant_a):
    views.CALLS["count"] = 0
    barrier = threading.Barrier(4)
    statuses: list[int] = []

    # Build clients (and the membership they need) before the threads start.
    clients = [api_client_for(staff_user, tenant_a) for _ in range(4)]

    def worker(client) -> None:
        barrier.wait()
        response = client.post(
            "/test-api/idempotent/",
            {"name": "c"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="race-0000001",
        )
        statuses.append(response.status_code)
        connection.close()

    threads = [threading.Thread(target=worker, args=(client,)) for client in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert statuses == [201, 201, 201, 201]
    assert Widget.objects.unscoped().count() == 1
    assert views.CALLS["count"] == 1


# --- sequences ----------------------------------------------------------------------------------
@pytest.mark.django_db
def test_sequences_are_per_tenant_name_and_period(tenant_a, tenant_b):
    with transaction.atomic(), tenant_context(tenant_a.id):
        assert [next_value("ORDER", "2026") for _ in range(3)] == [1, 2, 3]
        assert next_value("ORDER", "2027") == 1
        assert next_value("GRN", "2026") == 1
    with transaction.atomic(), tenant_context(tenant_b.id):
        assert next_value("ORDER", "2026") == 1


@pytest.mark.django_db
def test_sequence_rolls_back_without_gap(tenant_a):
    with tenant_context(tenant_a.id):
        with pytest.raises(RuntimeError), transaction.atomic():
            assert next_value("ORDER", "2026") == 1
            raise RuntimeError("business failure")
        with transaction.atomic():
            assert next_value("ORDER", "2026") == 1


def test_sequence_requires_transaction():
    with pytest.raises(RuntimeError):
        next_value("ORDER", "2026")


# --- outbox -------------------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
def test_outbox_dispatches_after_commit_to_registered_handlers(tenant_a):
    outbox.register_handler("test.happened", "tests.handler")
    with mock.patch("celery.current_app.send_task") as send_task:
        with transaction.atomic(), tenant_context(tenant_a.id):
            event = outbox.emit(
                "test.happened", aggregate_type="widget", aggregate_id=tenant_a.id, payload={"n": 1}
            )
            send_task.assert_not_called()  # nothing leaves before commit
        send_task.assert_called_once_with(
            "tests.handler", kwargs={"event_id": str(event.id), "tenant_id": str(tenant_a.id)}
        )
    event.refresh_from_db()
    assert event.dispatched_at is not None and event.attempts == 1


@pytest.mark.django_db(transaction=True)
def test_outbox_rolled_back_event_is_never_dispatched(tenant_a):
    with mock.patch("celery.current_app.send_task") as send_task:
        with pytest.raises(RuntimeError), transaction.atomic(), tenant_context(tenant_a.id):
            outbox.emit("test.happened", aggregate_type="widget", aggregate_id=tenant_a.id)
            raise RuntimeError("rollback")
        send_task.assert_not_called()
    assert OutboxEvent.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_outbox_sweeper_redispatches_after_broker_failure(tenant_a, settings):
    settings.OUTBOX_SWEEP_AFTER_SECONDS = 0
    outbox.register_handler("test.swept", "tests.handler")
    with (
        mock.patch.object(
            outbox.dispatch_event, "delay", side_effect=ConnectionError("broker down")
        ),
        transaction.atomic(),
        tenant_context(tenant_a.id),
    ):
        event = outbox.emit("test.swept", aggregate_type="widget", aggregate_id=tenant_a.id)
    event.refresh_from_db()
    assert event.dispatched_at is None
    with mock.patch("celery.current_app.send_task") as send_task:
        assert outbox.sweep_outbox() == 1
        send_task.assert_called_once()
    event.refresh_from_db()
    assert event.dispatched_at is not None


def test_emit_requires_transaction():
    with pytest.raises(RuntimeError):
        outbox.emit("x", aggregate_type="y", aggregate_id=None)  # type: ignore[arg-type]


# --- deadlock retry -----------------------------------------------------------------------------
def _deadlock() -> OperationalError:
    exc = OperationalError("deadlock detected")
    exc.__cause__ = pg_errors.DeadlockDetected()
    return exc


@pytest.mark.django_db(transaction=True)
def test_retry_on_deadlock_retries_then_succeeds():
    calls = {"n": 0}

    @retry_on_deadlock(attempts=3, base_delay=0)
    def service() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise _deadlock()
        return "done"

    assert service() == "done"
    assert calls["n"] == 3


@pytest.mark.django_db(transaction=True)
def test_retry_on_deadlock_gives_up_and_ignores_other_errors():
    @retry_on_deadlock(attempts=2, base_delay=0)
    def always_deadlocks() -> None:
        raise _deadlock()

    @retry_on_deadlock(attempts=3, base_delay=0)
    def other_error() -> None:
        raise OperationalError("connection lost")

    with pytest.raises(OperationalError):
        always_deadlocks()
    with pytest.raises(OperationalError, match="connection lost"):
        other_error()


# --- celery tenant task -------------------------------------------------------------------------
def _probe(*, tenant_id: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.current_tenant', true)")
        db_tenant = cursor.fetchone()[0]
    return f"{get_current_tenant_id()}|{db_tenant}"


probe_task = celery_app.task(base=TenantTask, name="tests.probe")(_probe)


@pytest.mark.django_db(transaction=True)
def test_tenant_task_sets_context_and_rls(tenant_a):
    result = probe_task.apply(kwargs={"tenant_id": str(tenant_a.id)}).get()
    assert result == f"{tenant_a.id}|{tenant_a.id}"
    assert get_current_tenant_id() is None  # context restored


def test_tenant_task_requires_tenant_id():
    with pytest.raises(ValueError, match="requires tenant_id"):
        probe_task.apply(kwargs={}).get()
