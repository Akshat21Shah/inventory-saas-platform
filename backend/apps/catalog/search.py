"""Product search (ADR-034): full-text on the trigger-maintained ``search_vector`` ('simple'
configuration, prefix matching for type-ahead) plus trigram similarity on name and code for typos.
"""

import re

from django.contrib.postgres.search import SearchQuery, SearchRank, TrigramWordSimilarity
from django.db.models import Case, Exists, F, FloatField, OuterRef, Q, QuerySet, Value, When
from django.db.models.functions import Greatest

from apps.catalog.models import Product, ProductBarcode

TYPEAHEAD_LIMIT = 20

# Word characters only: no tsquery operator (& | ! ( ) : * < > ') can reach the raw query.
_WORD = re.compile(r"\w+", re.UNICODE)


def prefix_query(text: str) -> SearchQuery | None:
    """``parle gluc`` → ``parle:* & gluc:*`` (every word, each as a prefix)."""
    words = _WORD.findall(text.lower())
    if not words:
        return None
    return SearchQuery(" & ".join(f"{w}:*" for w in words), search_type="raw", config="simple")


def search_filter(text: str) -> Q:
    text = text.strip()
    # Word similarity compares the typed text with the best-matching word ("magi" ~ "Maggi
    # Noodles"); plain similarity would compare it with the whole name. Both use the trigram index.
    condition = (
        Q(code__iexact=text)
        | Q(name__trigram_word_similar=text)
        | Q(code__trigram_word_similar=text)
    )
    query = prefix_query(text)
    if query is not None:
        condition |= Q(search_vector=query)
    return condition


def ranked(qs: QuerySet[Product], text: str, *, limit: int = TYPEAHEAD_LIMIT) -> list[Product]:
    """Best matches first: an exact code or barcode, then full-text rank plus trigram word
    similarity (so "magi" still finds "Maggi"), then name."""
    text = " ".join(text.split())[:100]
    if not text:
        return []
    query = prefix_query(text)
    rank = SearchRank(F("search_vector"), query) if query is not None else Value(0.0)
    similarity = Greatest(TrigramWordSimilarity(text, "name"), TrigramWordSimilarity(text, "code"))
    barcode = Exists(ProductBarcode.objects.filter(product=OuterRef("pk"), barcode=text))
    exact = Case(
        When(Q(code__iexact=text) | Q(barcode_match=True), then=Value(10.0)),
        default=Value(0.0),
        output_field=FloatField(),
    )
    return list(
        qs.annotate(barcode_match=barcode)
        .filter(search_filter(text) | Q(barcode_match=True))
        .annotate(score=exact + rank + similarity)
        .order_by("-score", "name", "id")[:limit]
    )
