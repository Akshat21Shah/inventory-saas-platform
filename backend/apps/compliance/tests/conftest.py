from typing import Any

import pytest

from apps.compliance.adapters.mock import MockGspClient
from apps.platform import selectors
from apps.platform.models import FeatureFlag, TenantFeature
from common.tenancy import tenant_context


@pytest.fixture(autouse=True)
def _fresh_mock_portal() -> Any:
    MockGspClient.reset()
    yield
    MockGspClient.reset()


def switch_on(tenant: Any, *codes: str) -> None:
    with tenant_context(tenant.pk):
        for code in codes:
            TenantFeature.objects.update_or_create(
                flag=FeatureFlag.objects.get(code=code), defaults={"enabled": True}
            )
    selectors.invalidate_tenant_features(tenant.pk)
