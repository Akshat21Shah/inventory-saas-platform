"""Demo e-invoicing, e-way bills and online payments for ``make seed`` (dev only, ADR-049).

Sharma Distributors gets all three modules with the mock GST provider and the test gateway, both
already checked, a ₹5 to 10 crore turnover band and a road distance on every shop address; Patel
Traders keeps them off, to show the app unchanged. Bills issued from now on get IRNs and e-way
bills from the mocks, and shops can pay online on the test gateway's page. Bills seeded earlier
have no IRN: staff can get one with "Get IRN". Idempotent.
"""

import json
from typing import Any

from apps.compliance.models import GstCredential
from apps.payments.models import GatewayConfig
from apps.platform.models import FeatureFlag, TenantFeature, TenantSetting
from apps.platform.selectors import invalidate_tenant_features, invalidate_tenant_settings
from apps.retailers.models import RetailerAddress

WITH_MODULES = ("sharma",)
MODULES = ("einvoice", "ewaybill", "payments")


def seed_compliance(tenant: Any) -> bool:
    """Returns whether the modules were switched on for this tenant."""
    if tenant.slug not in WITH_MODULES:
        return False
    for code in MODULES:
        TenantFeature.objects.update_or_create(
            flag=FeatureFlag.objects.get(code=code), defaults={"enabled": True}
        )
    invalidate_tenant_features(tenant.pk)
    TenantSetting.objects.update_or_create(
        key="compliance.turnover_band", defaults={"value": "FROM_5_TO_10_CR"}
    )
    invalidate_tenant_settings(tenant.pk)
    GstCredential.objects.update_or_create(
        provider="mock",
        defaults={
            "gstin": tenant.gstin,
            "environment": GstCredential.Environment.SANDBOX,
            "credentials": json.dumps({"username": "sharma_api", "password": "demo-password"}),
            "status": GstCredential.Status.VERIFIED,
        },
    )
    GatewayConfig.objects.update_or_create(
        defaults={
            "provider": GatewayConfig.Provider.MOCK,
            "mode": GatewayConfig.Mode.TEST,
            "key_id": "mock_sharma_key",
            "key_secret": "demo-key-secret",
            "webhook_secret": "demo-webhook-secret",
            "status": GatewayConfig.Status.VERIFIED,
        }
    )
    for address in RetailerAddress.objects.filter(distance_km__isnull=True).select_related(
        "retailer"
    ):
        same_state = address.state_id == tenant.state_id
        spread = int(address.pincode[-2:] or 0)  # stable per address
        address.distance_km = 8 + spread if same_state else 450 + spread * 4
        address.save(update_fields=["distance_km", "updated_at"])
    return True
