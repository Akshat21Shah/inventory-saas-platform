from collections.abc import Callable
from typing import Any

import pytest
from django.apps import apps as django_apps
from pytest_django.plugin import blocking_manager_key
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User
from apps.accounts.permissions import sync_permissions
from apps.platform.models import Tenant
from apps.platform.reference_data import seed_reference_data
from apps.platform.tests.factories import TenantFactory
from common.authentication import TENANT_CLAIM


def _is_transactional(item: pytest.Item) -> bool:
    marker = item.get_closest_marker("django_db")
    fixturenames = getattr(item, "fixturenames", ())
    return "transactional_db" in fixturenames or bool(marker and marker.kwargs.get("transaction"))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> Any:
    """Transactional tests flush every table, including migration-seeded reference data (states,
    tax rates, plans, flags, permissions, system roles). Re-seed after all fixture teardowns (i.e.
    after the flush)."""
    result = yield
    if _is_transactional(item):
        with item.config.stash[blocking_manager_key].unblock():
            seed_reference_data(django_apps)
            sync_permissions(django_apps)
    return result


@pytest.fixture
def make_tenant(db: Any) -> Callable[..., Tenant]:
    def factory(**kwargs: Any) -> Tenant:
        return TenantFactory.create(**kwargs)

    return factory


@pytest.fixture
def tenant_a(make_tenant: Callable[..., Tenant]) -> Tenant:
    return make_tenant(slug="alpha", name="Alpha")


@pytest.fixture
def tenant_b(make_tenant: Callable[..., Tenant]) -> Tenant:
    return make_tenant(slug="bravo", name="Bravo")


@pytest.fixture
def staff_user(db: Any) -> User:
    return User.objects.create_user(
        "staff@example.com", "a-strong-password", user_type=User.UserType.STAFF
    )


@pytest.fixture
def api_client_for() -> Callable[[User, Tenant | None], APIClient]:
    def factory(user: User, tenant: Tenant | None = None) -> APIClient:
        token = AccessToken.for_user(user)
        if tenant is not None:
            token[TENANT_CLAIM] = str(tenant.id)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    return factory
