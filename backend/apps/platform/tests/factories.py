"""Test factories for platform models. Generated GSTINs are checksum-valid and unique per run."""

from typing import Any

import factory
from factory.declarations import LazyAttribute, PostGeneration, Sequence

from apps.platform.models import Tenant
from apps.platform.validators import gstin_check_char


def make_gstin(n: int, state_code: str = "27") -> str:
    pan = make_pan(n)
    first14 = f"{state_code}{pan}1Z"
    return first14 + gstin_check_char(first14)


def make_pan(n: int) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return f"AA{letters[(n // 10000) % 26]}CT{n % 10000:04d}F"


class TenantFactory(factory.django.DjangoModelFactory[Tenant]):
    class Meta:
        model = Tenant
        skip_postgeneration_save = True

    name = Sequence(lambda n: f"Tenant {n}")
    legal_name = LazyAttribute(lambda o: f"{o.name} Private Limited")
    slug = Sequence(lambda n: f"tenant-{n}")
    status = Tenant.Status.ACTIVE
    state_id = "27"
    gstin = Sequence(lambda n: make_gstin(n))
    pan = LazyAttribute(lambda o: o.gstin[2:12])
    address_line1 = "12 Market Road"
    city = "Pune"
    pincode = "411001"
    email = Sequence(lambda n: f"owner{n}@example.com")
    phone = "9876543210"

    @classmethod
    def _adjust_kwargs(cls, **kwargs: Any) -> dict[str, Any]:
        # Keep GSTIN, PAN and state consistent when a test overrides only the state.
        state = kwargs.get("state_id") or getattr(kwargs.get("state"), "code", None)
        if state and not kwargs["gstin"].startswith(state):
            kwargs["gstin"] = state + kwargs["gstin"][2:14]
            kwargs["gstin"] += gstin_check_char(kwargs["gstin"])
        kwargs["pan"] = kwargs["gstin"][2:12]
        return kwargs

    default_units = PostGeneration(lambda obj, create, extracted, **kw: _default_units(obj, create))


def _default_units(tenant: Tenant, create: bool) -> None:
    """Like onboarding: every tenant starts with the default units and warehouse."""
    if not create:
        return
    from apps.catalog.defaults import ensure_default_units
    from apps.catalog.models import Unit
    from apps.inventory.defaults import ensure_default_warehouse
    from apps.inventory.models import Warehouse
    from common.tenancy import tenant_context

    with tenant_context(tenant.pk):
        ensure_default_units(Unit)
        ensure_default_warehouse(Warehouse)
