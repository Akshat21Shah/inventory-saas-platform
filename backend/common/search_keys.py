"""Search in either script (ADR-060 item 8). The database function ``search_key`` (common migration
0002) writes a name or a typed search, in English letters or Devanagari, in one spelling in English
letters: "चावल", "chawal" and "chaaval" all become "caval". Indexes are built on it and typed text
goes through the same function, so both sides always agree."""

from collections.abc import Sequence

from django.db import connection
from django.db.models import Func, TextField


class SearchKey(Func):
    """``search_key(<expression>)``: for filters, rankings and the indexes built on it."""

    function = "search_key"
    output_field = TextField()


def keys(texts: Sequence[str]) -> list[str]:
    """The key of each text, in order, in one round trip."""
    if not texts:
        return []
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT search_key(t) FROM unnest(%s::text[]) WITH ORDINALITY AS u(t, n) ORDER BY n",
            [list(texts)],
        )
        return [row[0] for row in cursor.fetchall()]


def key(text: str) -> str:
    return keys([text])[0]
