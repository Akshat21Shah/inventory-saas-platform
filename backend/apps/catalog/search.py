"""Product search (ADR-034): full-text on the trigger-maintained ``search_vector`` ('simple'
configuration, prefix matching for type-ahead) plus trigram similarity on name and code for typos.

In either script (ADR-060 item 8): the vector also holds each name in English letters
(``search_key``; the name's alone is kept in ``name_key``), and each typed word is looked for as
typed, in English letters, and as the other words for the same thing ("chawal" → "rice", "चावल",
"तांदूळ"): "टाटा" finds "Tata Salt", "chawal" finds "इंडिया गेट चावल" and "Basmati Rice".
"""

import re
from dataclasses import dataclass

from django.contrib.postgres.search import SearchQuery, SearchRank, TrigramWordSimilarity
from django.db.models import Case, F, FloatField, Q, QuerySet, Value, When
from django.db.models.functions import Greatest

from apps.catalog.models import Product, ProductBarcode
from apps.search.synonyms import other_words
from common.search_keys import keys

TYPEAHEAD_LIMIT = 20

# Words: letters and digits, with the vowel signs of Indian scripts (``\w`` alone splits "चावल" at
# "ा"), without the danda. No tsquery operator (& | ! ( ) : * < > ') can reach the raw query.
_WORD = re.compile(r"[\wऀ-ॣ०-෿]+")


@dataclass(frozen=True)
class Typed:
    """What was typed, ready to search: the text, its words, and each in English letters."""

    text: str
    words: tuple[str, ...]
    word_keys: tuple[str, ...]
    key: str  # the whole text in English letters


def typed(text: str) -> Typed:
    text = " ".join(text.split())[:100]
    words = tuple(_WORD.findall(text.lower()))
    found = keys([text, *words])
    return Typed(text, words, tuple(found[1:]), found[0])


def _options(word: str, word_key: str) -> list[str]:
    """``chawal`` → ``chawal:*``, ``caval:*`` and its other words' keys (``rike``, ``tandul``)."""
    options = [f"{word}:*"]
    in_letters = _WORD.findall(word_key)
    if len(in_letters) == 1 and in_letters[0] != word:
        options.append(f"{in_letters[0]}:*")
    options += sorted(k for k in other_words(word_key) if _WORD.fullmatch(k))
    return options


def prefix_query(found: Typed) -> SearchQuery | None:
    """``parle gluc`` → ``(parle:* | …) & (gluc:* | …)``: every word, each as a prefix, as typed
    or in English letters, or one of its other words."""
    if not found.words:
        return None
    raw = " & ".join(
        "(" + " | ".join(_options(word, word_key)) + ")"
        for word, word_key in zip(found.words, found.word_keys, strict=True)
    )
    return SearchQuery(raw, search_type="raw", config="simple")


def search_filter(text: str | Typed) -> Q:
    found = text if isinstance(text, Typed) else typed(text)
    # Word similarity compares the typed text with the best-matching word ("magi" ~ "Maggi
    # Noodles"); plain similarity would compare it with the whole name. Names are compared in
    # English letters, which also catches typos across scripts ("मैगी" ~ "Maggi"; other scripts
    # pass through unchanged). An exact code is the most similar.
    name = (
        Q(name_key__trigram_word_similar=found.key)
        if found.key.strip()
        else Q(name__trigram_word_similar=found.text)
    )
    condition = name | Q(code__trigram_word_similar=found.text)
    query = prefix_query(found)
    if query is not None:
        condition |= Q(search_vector=query)
    return condition


def ranked_queryset(qs: QuerySet[Product], text: str) -> QuerySet[Product]:
    """Matches ordered best first: an exact code or barcode, then full-text rank plus trigram word
    similarity (so "magi" still finds "Maggi"), then name. Empty text matches nothing."""
    found = typed(text)
    if not found.text:
        return qs.none()
    text = found.text
    query = prefix_query(found)
    rank = SearchRank(F("search_vector"), query) if query is not None else Value(0.0)
    similarity = Greatest(
        TrigramWordSimilarity(text, "name"),
        TrigramWordSimilarity(found.key, "name_key"),
        TrigramWordSimilarity(text, "code"),
    )
    # Looked up first, so the search itself stays on indexes.
    barcode = list(ProductBarcode.objects.filter(barcode=text).values_list("product_id", flat=True))
    condition = search_filter(found) | Q(pk__in=barcode) if barcode else search_filter(found)
    exact = Case(
        When(Q(code__iexact=text) | Q(pk__in=barcode), then=Value(10.0)),
        default=Value(0.0),
        output_field=FloatField(),
    )
    return (
        qs.filter(condition)
        .annotate(score=exact + rank + similarity)
        .order_by("-score", "name", "id")
    )


def ranked(qs: QuerySet[Product], text: str, *, limit: int = TYPEAHEAD_LIMIT) -> list[Product]:
    return list(ranked_queryset(qs, text)[:limit])
