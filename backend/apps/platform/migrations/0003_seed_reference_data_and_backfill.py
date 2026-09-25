"""Seed platform reference data and backfill tenants created by the Phase 0 stub.

- GST state codes, the GST rate master (ADR-008), the default "BETA" plan and the feature flags.
- Tenants that existed before Phase 1 (dev seed data only) get placeholder business details so the
  columns can become NOT NULL in 0004, plus their profile, branding and Beta subscription rows.
"""

from django.db import migrations
from django.utils import timezone

from apps.platform.reference_data import seed_reference_data

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _check_char(first14):
    total = 0
    for index, char in enumerate(first14):
        product = _ALPHABET.index(char) * (1 if index % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _ALPHABET[(36 - total % 36) % 36]


def seed(apps, schema_editor):
    seed_reference_data(apps)


def backfill_tenants(apps, schema_editor):
    import secrets

    Tenant = apps.get_model("platform", "Tenant")
    TenantProfile = apps.get_model("platform", "TenantProfile")
    TenantBranding = apps.get_model("platform", "TenantBranding")
    Subscription = apps.get_model("platform", "Subscription")
    Plan = apps.get_model("platform", "Plan")
    beta = Plan.objects.get(code="BETA")

    for n, tenant in enumerate(Tenant.objects.order_by("created_at"), start=1):
        if tenant.webhook_token is None:
            tenant.webhook_token = secrets.token_urlsafe(32)
        if tenant.gstin is None:
            # Placeholder identity for pre-Phase-1 dev tenants only (clearly fake, checksum-valid).
            pan = f"ZZZCZ{n:04d}Z"
            first14 = f"27{pan}1Z"
            tenant.gstin = first14 + _check_char(first14)
            tenant.pan = pan
            tenant.state_id = "27"
            tenant.legal_name = tenant.legal_name or tenant.name
            tenant.address_line1 = "Address not set"
            tenant.city = "Mumbai"
            tenant.pincode = "400001"
            tenant.email = f"{tenant.slug}@example.invalid"
            tenant.phone = "0000000000"
        tenant.save()
        TenantProfile.objects.get_or_create(tenant_id=tenant.id)
        TenantBranding.objects.get_or_create(
            tenant_id=tenant.id, defaults={"display_name": tenant.name}
        )
        if not Subscription.objects.filter(tenant_id=tenant.id, is_current=True).exists():
            Subscription.objects.create(
                tenant_id=tenant.id, plan_id=beta.id, status="ACTIVE", starts_at=timezone.now()
            )


class Migration(migrations.Migration):
    dependencies = [
        ("platform", "0002_tenant_profile_masters_plans_flags"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
        migrations.RunPython(backfill_tenants, migrations.RunPython.noop),
    ]
