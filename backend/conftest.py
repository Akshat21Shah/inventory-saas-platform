from collections.abc import Callable
from typing import Any

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User
from apps.platform.models import Tenant
from common.authentication import TENANT_CLAIM


@pytest.fixture
def make_tenant(db: Any) -> Callable[..., Tenant]:
    counter = {"n": 0}

    def factory(**kwargs: Any) -> Tenant:
        counter["n"] += 1
        n = counter["n"]
        defaults = {"name": f"Tenant {n}", "slug": f"tenant-{n}", "status": Tenant.Status.ACTIVE}
        defaults.update(kwargs)
        return Tenant.objects.create(**defaults)

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
