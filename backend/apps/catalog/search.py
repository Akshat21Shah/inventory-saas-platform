"""Product search (ADR-034): full-text on the trigger-maintained ``search_vector`` ('simple'
configuration, prefix matching for type-ahead) plus trigram similarity on name and code for typos.
"""

import re

from django.contrib.postgres.search import SearchQuery
from django.db.models import Q

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
