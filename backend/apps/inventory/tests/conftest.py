from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _no_eager_dispatch_in_threads(request: pytest.FixtureRequest, monkeypatch: Any) -> None:
    """Threaded tests commit for real, so outbox events would be dispatched by eager Celery from
    several threads at once. Celery's "inside a task" flag is a process global that concurrent
    eager tasks can leave set, which breaks later tests. The events are still written (and
    asserted on); only the after-commit enqueue is skipped, as the sweeper would do it."""
    if request.node.get_closest_marker("concurrency"):
        monkeypatch.setattr("common.outbox._safe_enqueue", lambda event_id: None)
