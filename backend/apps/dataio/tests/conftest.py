import pytest
from django.core.cache import cache

from apps.dataio.tests.helpers import _client
from common.storage import InMemoryStorage


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    InMemoryStorage.objects.clear()
    yield
    cache.clear()
    InMemoryStorage.objects.clear()


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    """Call a view and run its on-commit tasks (Celery is eager in tests)."""

    def _run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return _run


@pytest.fixture
def owner(tenant_a):
    return _client(tenant_a)
