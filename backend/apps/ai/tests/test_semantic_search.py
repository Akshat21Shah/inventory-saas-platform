"""AI foundation and semantic search (ADR-058): the mock embeddings, product embeddings kept up to
date, the shop's search adding near matches after keyword matches, usage recorded, the monthly cap
and provider failures falling back to today's search, the module off, and isolation."""

from decimal import Decimal as D
from typing import Any

import pytest
from django.core.cache import cache

from apps.ai import services
from apps.ai.adapters import mock
from apps.ai.models import AiUsage, ProductEmbedding
from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import add_stock, make_shop, shop_client
from apps.platform.models import FeatureFlag, TenantFeature
from apps.platform.selectors import invalidate_tenant_features
from apps.platform.services import set_platform_settings
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
SHOP = "/api/v1/shop"


def switch(tenant: Any, on: bool = True) -> None:
    with tenant_context(tenant.pk):
        TenantFeature.objects.update_or_create(
            flag=FeatureFlag.objects.get(code="ai"), defaults={"enabled": on}
        )
    invalidate_tenant_features(tenant.pk)


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_the_mock_puts_spelling_slips_near_and_other_things_far():
    noodles = mock.vector("Maggi Masala Noodles 70g")
    assert cosine(mock.vector("magi nodles"), noodles) > 0.4
    assert cosine(mock.vector("washing powder"), noodles) < 0.2
    assert mock.vector("Maggi") == mock.vector("maggi")  # deterministic, case-blind


@pytest.fixture
def world(tenant_a, tenant_b):
    cache.clear()
    switch(tenant_a)
    products = {
        "noodles": make_product(
            tenant_a, "N-1", name="Maggi Masala Noodles 70g", base_price=D("14")
        ),
        "salt": make_product(tenant_a, "S-1", name="Tata Salt 1kg", base_price=D("28")),
        "soap": make_product(tenant_a, "SP-1", name="Lux Soap Bar", base_price=D("40")),
    }
    for product in products.values():
        add_stock(tenant_a, product, "10")
    shop = make_shop(tenant_a, "9876500141")
    yield {"t": tenant_a, "b": tenant_b, "shop": shop, **products}
    cache.clear()


def embed_all(tenant: Any) -> int:
    with tenant_context(tenant.pk):
        return services.refresh_embeddings()


def names(response: Any) -> list[str]:
    return [p["name"] for p in response.json()["results"]]


def test_embeddings_are_made_once_and_remade_when_the_text_changes(world):
    assert embed_all(world["t"]) == 3
    assert embed_all(world["t"]) == 0  # nothing changed
    with tenant_context(world["t"].pk):
        world["salt"].name = "Tata Salt Lite 1kg"
        world["salt"].save(update_fields=["name"])
    assert embed_all(world["t"]) == 1
    with tenant_context(world["t"].pk):
        usage = list(AiUsage.objects.values_list("feature", "ok", "units_in"))
    assert [(f, ok) for f, ok, _ in usage] == [("SEARCH_INDEX", True)] * 2
    assert all(units > 0 for _, _, units in usage)


def test_the_shop_finds_a_misspelt_product_after_keyword_matches(world):
    client = shop_client(world["t"], world["shop"])
    assert names(client.get(f"{SHOP}/products/", {"search": "magi nodles"})) == []
    embed_all(world["t"])
    found = names(client.get(f"{SHOP}/products/", {"search": "magi nodles"}))
    assert found == ["Maggi Masala Noodles 70g"]
    # Keyword matches keep coming first.
    assert names(client.get(f"{SHOP}/products/", {"search": "salt"}))[0] == "Tata Salt 1kg"
    with tenant_context(world["t"].pk):
        assert AiUsage.objects.filter(feature="SEARCH_QUERY").count() == 2


def test_over_the_monthly_cap_or_when_the_provider_fails_search_works_as_before(world, monkeypatch):
    embed_all(world["t"])
    client = shop_client(world["t"], world["shop"])
    set_platform_settings({"platform.ai_monthly_units": 1}, user=None)
    cache.clear()
    assert names(client.get(f"{SHOP}/products/", {"search": "magi nodles"})) == []
    set_platform_settings({"platform.ai_monthly_units": 0}, user=None)  # 0: no cap
    cache.clear()

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise TimeoutError("took too long")

    monkeypatch.setattr(mock.MockEmbeddings, "embed", broken)
    assert names(client.get(f"{SHOP}/products/", {"search": "magi nodles"})) == []
    assert names(client.get(f"{SHOP}/products/", {"search": "salt"})) == ["Tata Salt 1kg"]
    with tenant_context(world["t"].pk):
        failed = AiUsage.objects.filter(ok=False).values_list("error", flat=True)
    assert list(failed)[-1] == "took too long"


def test_switched_off_nothing_is_embedded_or_sent(world):
    switch(world["t"], False)
    assert embed_all(world["t"]) == 0
    client = shop_client(world["t"], world["shop"])
    assert names(client.get(f"{SHOP}/products/", {"search": "magi nodles"})) == []
    with tenant_context(world["t"].pk):
        assert not AiUsage.objects.exists() and not ProductEmbedding.objects.exists()


def test_another_distributors_products_are_never_near(world):
    switch(world["b"])
    other = make_product(world["b"], "N-9", name="Maggi Masala Noodles 70g", base_price=D("14"))
    add_stock(world["b"], other, "5")
    embed_all(world["b"])
    with tenant_context(world["t"].pk):
        assert not ProductEmbedding.objects.exists()  # tenant A's view (RLS)
    client = shop_client(world["t"], world["shop"])
    assert names(client.get(f"{SHOP}/products/", {"search": "magi nodles"})) == []
