"""Product search (ADR-034): ranking, typos, codes and barcodes, isolation, and the < 200 ms
target on 20,000 products."""

import random
import statistics
import time
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.db import connection
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in
from apps.accounts.tokens import issue_tokens
from apps.catalog import search, selectors
from apps.catalog.models import Brand, Product, ProductBarcode, Unit
from common.tenancy import tenant_context, tenant_transaction
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


def _make(tenant, code, name, brand=None, tags=()):
    with tenant_context(tenant.pk):
        return Product.objects.create(
            code=code,
            name=name,
            brand=brand,
            tags=list(tags),
            unit=Unit.objects.get(code="PCS"),
            hsn_code="1905",
            base_price=Decimal("10"),
        )


def _codes(tenant, text):
    with tenant_context(tenant.pk):
        return [p.code for p in search.ranked(selectors.product_list(), text)]


def test_ranking_prefers_exact_codes_then_relevance(tenant_a):
    with tenant_context(tenant_a.pk):
        parle = Brand.objects.create(name="Parle")
    _make(tenant_a, "PG-100", "Glucose Biscuits 100g", brand=parle)
    _make(tenant_a, "PG-250", "Glucose Biscuits 250g", brand=parle)
    _make(tenant_a, "MG-70", "Maggi Masala Noodles 70g", tags=["instant"])
    _make(tenant_a, "BRU-1", "Bru Instant Coffee 50g")

    assert _codes(tenant_a, "pg-250")[0] == "PG-250"  # exact code first
    assert set(_codes(tenant_a, "parle")) == {"PG-100", "PG-250"}  # brand
    assert _codes(tenant_a, "gluc bisc 250")[0] == "PG-250"  # word prefixes
    assert _codes(tenant_a, "magi")[0] == "MG-70"  # typo
    assert set(_codes(tenant_a, "instant")) == {"MG-70", "BRU-1"}  # tag and name
    with tenant_context(tenant_a.pk):
        ProductBarcode.objects.create(product=Product.objects.get(code="BRU-1"), barcode="890123")
    assert _codes(tenant_a, "890123") == ["BRU-1"]
    assert _codes(tenant_a, "   ") == []
    assert _codes(tenant_a, "!!& :*") == []  # tsquery operators can't break the query


@covers("catalog-product-search")
def test_search_endpoint_is_tenant_scoped(tenant_a, tenant_b):
    _make(tenant_a, "A-1", "Tata Salt 1kg")
    _make(tenant_b, "B-1", "Tata Salt 1kg")
    for tenant, code in ((tenant_a, "A-1"), (tenant_b, "B-1")):
        client = APIClient()
        token = issue_tokens(make_staff_in(tenant, "SALES"), tenant.pk).access
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        client.defaults["HTTP_X_FORWARDED_HOST"] = f"{tenant.slug}.localhost"
        rows = client.get("/api/v1/products/search/", {"q": "tata salt"}).json()
        assert [r["code"] for r in rows] == [code]


# --- Performance -------------------------------------------------------------------------------

BRANDS = [
    "Parle",
    "Britannia",
    "Amul",
    "Tata",
    "Nestle",
    "Dabur",
    "Haldiram",
    "Patanjali",
    "Colgate",
    "Surf",
    "Maggi",
    "Kissan",
    "Everest",
    "MDH",
    "Fortune",
    "Aashirvaad",
]
KINDS = [
    "Biscuits",
    "Noodles",
    "Salt",
    "Tea",
    "Coffee",
    "Soap",
    "Shampoo",
    "Toothpaste",
    "Namkeen",
    "Atta",
    "Oil",
    "Ghee",
    "Masala",
    "Jam",
    "Ketchup",
    "Detergent",
    "Chocolate",
    "Juice",
    "Rice",
    "Dal",
]
VARIANTS = [
    "Classic",
    "Gold",
    "Premium",
    "Lite",
    "Masala",
    "Elaichi",
    "Herbal",
    "Family pack",
    "Value pack",
    "Kesar",
    "Rose",
    "Lemon",
    "Mango",
    "Plain",
    "Special",
]
SIZES = ["50g", "100g", "200g", "250g", "500g", "1kg", "5kg", "100ml", "500ml", "1L"]


@pytest.mark.django_db(transaction=True)
def test_search_answers_within_200ms_on_20000_products(make_tenant):
    tenant, other = make_tenant(slug="perf-a"), make_tenant(slug="perf-b")
    rng = random.Random(42)
    for target, count in ((tenant, 20_000), (other, 2_000)):
        with tenant_context(target.pk):
            unit = Unit.objects.get(code="PCS")
            brands = [Brand.objects.create(name=b) for b in BRANDS]
            Product.objects.bulk_create(
                [
                    Product(
                        tenant_id=target.pk,
                        code=f"P-{n:06d}",
                        unit=unit,
                        hsn_code="1905",
                        brand=rng.choice(brands),
                        base_price=Decimal("10"),
                        name=f"{rng.choice(KINDS)} {rng.choice(VARIANTS)} {rng.choice(SIZES)}",
                        tags=[rng.choice(VARIANTS).lower()],
                    )
                    for n in range(count)
                ],
                batch_size=2000,
            )
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE catalog_product")
    queries = [
        "parle",
        "biscuits gold",
        "masla",
        "tea elaichi 250g",
        "P-012345",
        "surf deter",
        "choco",
        "haldiram namkeen",
        "atta 5kg",
        "xyz-not-there",
    ]
    timings = []
    # As in production: the runtime role, with RLS applying the tenant inside a transaction.
    with tenant_transaction(tenant.pk):
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE app_user")
        search.ranked(selectors.product_list(), "warm up")
        for text in queries:
            # Median of five: the query's typical cost, not one scheduling hiccup on a shared
            # CI runner.
            runs = []
            for _ in range(5):
                started = time.perf_counter()
                results = search.ranked(selectors.product_list(), text)
                runs.append((time.perf_counter() - started) * 1000)
                assert all(p.tenant_id == tenant.pk for p in results)
            timings.append(statistics.median(runs))
        best = search.ranked(selectors.product_list(), "P-012345")[0]
        assert best.code == "P-012345"
    report = [f"{q}: {t:.0f} ms" for q, t in zip(queries, timings, strict=True)]
    print("search timings:", report)
    assert max(timings) < 200, report
