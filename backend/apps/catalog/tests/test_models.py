"""Catalog data rules enforced by the database (PLAN §2.4): levels, uniqueness, product checks,
the search vector trigger and the append-only GST-rate history (ADR-034)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.postgres.search import SearchQuery
from django.db import IntegrityError, InternalError, transaction
from django.utils import timezone

from apps.catalog.defaults import DEFAULT_UNITS
from apps.catalog.models import (
    Brand,
    Category,
    Product,
    ProductBarcode,
    ProductTaxRate,
    Unit,
)
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


def _product(**kwargs):
    unit = Unit.objects.get(code="PCS")
    fields = {
        "code": "P-1",
        "name": "Parle-G 100g",
        "unit": unit,
        "hsn_code": "1905",
        "base_price": Decimal("10.00"),
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


def _fails(fn):
    with pytest.raises((IntegrityError, InternalError)), transaction.atomic():
        fn()


def test_every_tenant_starts_with_the_default_units(tenant_a, tenant_b):
    for tenant in (tenant_a, tenant_b):
        with tenant_context(tenant.pk):
            assert set(Unit.objects.values_list("code", flat=True)) >= {
                c for c, *_ in DEFAULT_UNITS
            }


def test_category_levels_and_unique_names(tenant_a):
    with tenant_context(tenant_a.pk):
        food = Category.objects.create(name="Food", slug="food")
        Category.objects.create(name="Biscuits", slug="biscuits", parent=food, level=2)
        _fails(lambda: Category.objects.create(name="biscuits", slug="b2", parent=food, level=2))
        _fails(lambda: Category.objects.create(name="Other", slug="o", level=4, parent=food))
        _fails(lambda: Category.objects.create(name="Root", slug="r", level=2))
        _fails(lambda: Category.objects.create(name="FOOD", slug="food-2"))  # top level too
        food.deleted_at = timezone.now()
        food.save()
        Category.objects.create(name="Food", slug="food-3")  # a deleted name can be reused


def test_product_checks_and_codes_are_never_reused(tenant_a):
    with tenant_context(tenant_a.pk):
        product = _product()
        _fails(lambda: _product(code="p-1"))  # case-insensitive
        product.deleted_at = timezone.now()
        product.save()
        _fails(lambda: _product(code="P-1"))  # not even after deletion
        _fails(lambda: _product(code="P-2", base_price=Decimal("-1")))
        _fails(lambda: _product(code="P-3", min_order_qty=Decimal("0")))
        _fails(lambda: _product(code="P-4", pack_unit=Unit.objects.get(code="BOX")))
        _fails(lambda: _product(code="P-5", hsn_code="19A5"))
        box = _product(code="P-6", pack_unit=Unit.objects.get(code="BOX"), pack_size=Decimal("12"))
        assert box.show_in_shop is True


def test_search_vector_follows_name_barcodes_brand_and_category(tenant_a):
    with tenant_context(tenant_a.pk):
        brand = Brand.objects.create(name="Parle")
        category = Category.objects.create(name="Biscuits", slug="biscuits")
        product = _product(
            code="PG100", name="Tiger 100g", brand=brand, category=category, tags=["glucose"]
        )

        def matches(term: str) -> bool:
            query = SearchQuery(term, config="simple")
            return Product.objects.filter(pk=product.pk, search_vector=query).exists()

        assert all(matches(t) for t in ("parle", "biscuits", "glucose", "pg100"))
        ProductBarcode.objects.create(product=product, barcode="8901719101038")
        assert matches("8901719101038")
        brand.name = "Britannia"
        brand.save()
        category.name = "Cookies"
        category.save()
        assert matches("britannia") and matches("cookies") and not matches("parle")
        ProductBarcode.objects.filter(product=product).delete()
        assert not matches("8901719101038")


def test_tax_rate_history_is_append_only_except_cancelling(tenant_a):
    with tenant_context(tenant_a.pk):
        product = _product()
        today = date.today()
        ProductTaxRate.objects.create(product=product, gst_rate=Decimal("18"), effective_from=today)
        future = ProductTaxRate.objects.create(
            product=product, gst_rate=Decimal("5"), effective_from=today + timedelta(days=7)
        )
        _fails(lambda: ProductTaxRate.objects.filter(pk=future.pk).update(gst_rate=Decimal("12")))
        _fails(lambda: ProductTaxRate.objects.filter(pk=future.pk).delete())
        _fails(  # a second row for the same day
            lambda: ProductTaxRate.objects.create(
                product=product, gst_rate=Decimal("3"), effective_from=future.effective_from
            )
        )
        ProductTaxRate.objects.filter(pk=future.pk).update(
            cancelled_at=timezone.now(), cancel_reason="Scheduled by mistake"
        )
        _fails(lambda: ProductTaxRate.objects.filter(pk=future.pk).update(cancelled_at=None))
        # After cancelling, that day can be scheduled again.
        ProductTaxRate.objects.create(
            product=product, gst_rate=Decimal("3"), effective_from=future.effective_from
        )
