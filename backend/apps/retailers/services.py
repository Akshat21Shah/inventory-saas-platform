"""Retailer write logic. PHASE 1: creating a retailer with its sign-in login (tests, seed, and the
onboarding of Phase 2 build on this)."""

from django.db import transaction

from apps.accounts.models import User
from apps.retailers.models import Retailer, RetailerUser
from common.phone import normalize_indian_mobile
from common.tenancy import require_tenant_id


@transaction.atomic
def create_retailer(
    *, shop_name: str, phone: str, contact_name: str = "", created_by: User | None = None
) -> Retailer:
    """A retailer in the active tenant with one RETAILER login (unique by phone per tenant)."""
    tenant_id = require_tenant_id()
    mobile = normalize_indian_mobile(phone)
    retailer: Retailer = Retailer.objects.create(
        shop_name=shop_name.strip(),
        contact_name=contact_name.strip(),
        phone=mobile,
        created_by=created_by,
    )
    user = User.objects.create_user(
        None,
        None,
        user_type=User.UserType.RETAILER,
        phone=mobile,
        tenant_id=tenant_id,
        full_name=contact_name.strip(),
    )
    RetailerUser.objects.create(retailer=retailer, user=user, created_by=created_by)
    return retailer
