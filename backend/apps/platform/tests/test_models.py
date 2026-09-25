"""Database-level invariants of platform models (check constraints, uniqueness, RLS)."""

from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.platform.models import (
    Plan,
    State,
    Subscription,
    TaxRate,
    Tenant,
    TenantBranding,
    TenantFeature,
    TenantProfile,
)
from apps.platform.tests.factories import TenantFactory, make_gstin
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


def _violates(**updates):
    tenant = TenantFactory.create()
    with pytest.raises(IntegrityError), transaction.atomic():
        Tenant.objects.filter(pk=tenant.pk).update(**updates)


def test_gstin_must_start_with_state_code():
    _violates(state_id="24")


def test_pan_must_match_gstin():
    _violates(pan="AAPFU0939F")


def test_only_regular_registration_is_allowed():
    _violates(registration_type=Tenant.RegistrationType.COMPOSITION)


@pytest.mark.parametrize("slug", ["Upper", "-bad", "a"])
def test_slug_format_enforced_in_database(slug):
    _violates(slug=slug)


def test_gstin_format_and_pincode_enforced_in_database():
    _violates(gstin="27aapfu0939f1zv")
    _violates(pincode="012345")


def test_gstin_and_webhook_token_are_unique():
    first = TenantFactory.create()
    assert len(first.webhook_token) >= 40
    with pytest.raises(IntegrityError), transaction.atomic():
        TenantFactory.create(gstin=first.gstin)
    second = TenantFactory.create()
    assert second.webhook_token != first.webhook_token


def test_factory_keeps_gstin_pan_and_state_consistent():
    tenant = TenantFactory.create(state_id="24")
    assert tenant.gstin.startswith("24")
    assert tenant.pan == tenant.gstin[2:12]
    tenant.full_clean()


def test_only_one_default_plan():
    assert Plan.objects.filter(is_default=True).count() == 1
    with pytest.raises(IntegrityError), transaction.atomic():
        Plan.objects.create(code="OTHER", name="Other", is_default=True)


def test_tax_rate_range_and_uniqueness():
    with pytest.raises(IntegrityError), transaction.atomic():
        TaxRate.objects.create(rate=Decimal("101"), label="bad")
    with pytest.raises(IntegrityError), transaction.atomic():
        TaxRate.objects.create(rate=Decimal("18"), label="dup")


def test_one_profile_branding_and_current_subscription_per_tenant():
    tenant = TenantFactory.create()
    beta = Plan.objects.get(code="BETA")
    with tenant_context(tenant.id):
        TenantProfile.objects.create(bank_account_number="123456789012")
        TenantBranding.objects.create(display_name="X")
        Subscription.objects.create(plan=beta, starts_at=timezone.now())
        for create in (
            lambda: TenantProfile.objects.create(),
            lambda: TenantBranding.objects.create(),
            lambda: Subscription.objects.create(plan=beta, starts_at=timezone.now()),
        ):
            with pytest.raises(IntegrityError), transaction.atomic():
                create()
        # A past (non-current) subscription is allowed alongside the current one.
        Subscription.objects.create(plan=beta, starts_at=timezone.now(), is_current=False)


def test_branding_colour_must_be_lowercase_hex():
    tenant = TenantFactory.create()
    with (
        tenant_context(tenant.id),
        pytest.raises(IntegrityError),
        transaction.atomic(),
    ):
        TenantBranding.objects.create(primary_color="blue")


def test_bank_account_number_is_encrypted_at_rest():
    tenant = TenantFactory.create()
    with tenant_context(tenant.id):
        profile = TenantProfile.objects.create(bank_account_number="123456789012")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT bank_account_number FROM platform_tenantprofile WHERE id = %s", [profile.pk]
        )
        assert "123456789012" not in cursor.fetchone()[0]
    with tenant_context(tenant.id):
        assert TenantProfile.objects.get().bank_account_number == "123456789012"


@pytest.mark.parametrize("model", [TenantProfile, TenantBranding, Subscription, TenantFeature])
def test_tenant_owned_platform_tables_are_tenant_scoped(model):
    assert "tenant" in {f.name for f in model._meta.fields}
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity FROM pg_class WHERE relname = %s", [model._meta.db_table]
        )
        assert cursor.fetchone()[0] is True


def test_state_codes_are_two_digits():
    with pytest.raises(IntegrityError), transaction.atomic():
        State.objects.create(code="AB", name="Bad")


def test_make_gstin_is_unique_per_number():
    assert len({make_gstin(n) for n in range(2000)}) == 2000
