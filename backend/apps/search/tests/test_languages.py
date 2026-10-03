"""Search in either script (ADR-060 item 8): a product, shop, staff member or supplier named in
Devanagari is found by its name typed in English letters and the other way round; everyday words
find their thing in any language ("chawal", "चावल" and "तांदूळ" find "Basmati Rice"); Devanagari
words are matched as they are being typed; the word lists are complete and never give one word to
two things."""

import json
import re
from decimal import Decimal as D

import pytest

from apps.accounts.models import User
from apps.accounts.tests.factories import make_staff_in
from apps.catalog import search as product_search
from apps.catalog import selectors as catalog
from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import make_shop
from apps.purchasing import selectors as purchasing
from apps.purchasing.services import create_supplier
from apps.retailers.models import Retailer
from apps.retailers.selectors import RetailerFilters, retailers_for
from apps.search import selectors, synonyms
from apps.search.synonyms import WORDS_DIR
from common.search_keys import keys
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


@pytest.fixture
def world(tenant_a, tenant_b):
    owner = make_staff_in(tenant_a, "OWNER")
    for code, name in (
        ("RICE", "Basmati Rice 5kg"),
        ("CHAWAL", "इंडिया गेट चावल 1kg"),
        ("SALT", "Tata Salt 1kg"),
        ("NAMAK", "टाटा नमक 1kg"),
        ("TEA", "Wagh Bakri Tea 250g"),
        ("NAMKEEN", "हल्दीराम नमकीन 200g"),
    ):
        make_product(tenant_a, code, name=name, base_price=D("10"))
    make_product(tenant_b, "OTHER", name="Other Basmati Rice", base_price=D("10"))
    return {"t": tenant_a, "owner": owner}


def _codes(world, text: str) -> list[str]:
    with tenant_context(world["t"].pk):
        return [p.code for p in product_search.ranked(catalog.product_list(), text)]


@pytest.mark.parametrize(
    ("typed", "finds"),
    [
        ("टाटा", {"SALT", "NAMAK"}),  # Devanagari finds the English name
        ("tata", {"SALT", "NAMAK"}),  # and English letters the Devanagari one
        ("haldiram", {"NAMKEEN"}),
        ("namkeen", {"NAMKEEN"}),
        ("chawal", {"RICE", "CHAWAL"}),  # Hinglish: its thing in every language
        ("तांदूळ", {"RICE", "CHAWAL"}),  # Marathi
        ("rice", {"RICE", "CHAWAL"}),
        ("मीठ", {"SALT", "NAMAK"}),
        ("chai", {"TEA"}),
        ("चाव", {"CHAWAL"}),  # a Devanagari word while it is being typed
        ("namak 1kg", {"SALT", "NAMAK"}),  # every word must match
    ],
)
def test_products_are_found_in_either_script(world, typed, finds):
    found = _codes(world, typed)
    assert finds <= set(found), (typed, found)
    assert "OTHER" not in found  # never another distributor's


def test_the_better_match_comes_first(world):
    assert _codes(world, "टाटा नमक")[0] == "NAMAK"
    assert _codes(world, "tata salt")[0] == "SALT"


def test_shops_staff_and_suppliers_are_found_in_either_script(world):
    shop = make_shop(world["t"], "9876500181", shop_name="गणेश किराना")
    with tenant_context(world["t"].pk):
        Retailer.objects.filter(pk=shop.pk).update(owner_name="Suresh Patil")
        User.objects.filter(pk=world["owner"].pk).update(full_name="सुरेश पाटील")
        create_supplier({"name": "महालक्ष्मी ट्रेडर्स"}, by=world["owner"])
        found = selectors.search(world["owner"], "ganesh kirana")
        assert [h.title for g in found.groups if g.type == "shop" for h in g.hits] == ["गणेश किराना"]
        by_owner = selectors.search(world["owner"], "सुरेश")  # the shop's owner, in Devanagari
        assert shop.pk in {h.id for g in by_owner.groups if g.type == "shop" for h in g.hits}
        staff = selectors.search(world["owner"], "suresh patil")
        assert "सुरेश पाटील" in {h.title for g in staff.groups if g.type == "staff" for h in g.hits}
        # The shops list too.
        assert list(retailers_for(world["owner"], RetailerFilters(search="Ganesh"))) == [shop]
        assert [s.name for s in purchasing.suppliers(search="mahalaxmi traders")] == [
            "महालक्ष्मी ट्रेडर्स"
        ]


def test_the_word_lists_are_complete_and_each_word_names_one_thing():
    english = json.loads((WORDS_DIR / "en.json").read_text("utf-8"))
    for path in sorted(WORDS_DIR.glob("*.json")):
        table = json.loads(path.read_text("utf-8"))
        assert set(table) <= set(english), path.name  # every thing is listed in en.json
        for thing, words in table.items():
            assert words == list(dict.fromkeys(words)), (path.name, thing)  # no repeats
            for word in words:
                assert word and " " not in word and word == word.lower(), (path.name, word)
            if path.stem != "en":
                assert any(DEVANAGARI.search(w) for w in words), (path.name, thing)
    assert len(english) >= 80
    assert sum(len(json.loads(p.read_text("utf-8"))) for p in WORDS_DIR.glob("*.json")) >= 200

    # No key may name two things: "gud" (jaggery) can't also be another thing's word.
    table = synonyms.things()
    words = [(thing, word) for thing, group in table.items() for word in group]
    owners: dict[str, set[str]] = {}
    for (thing, _), word_key in zip(words, keys([w for _, w in words]), strict=True):
        owners.setdefault(word_key, set()).add(thing)
    assert {k: v for k, v in owners.items() if len(v) > 1} == {}
