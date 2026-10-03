"""Everyday trade words in each language (ADR-060 item 8; one platform-wide list, owner): typing
"chawal", "चावल" or "तांदूळ" also finds "Basmati Rice", and "rice" finds "इंडिया गेट चावल".

``words/en.json`` lists the things (each an English word) and their other English words;
``words/<code>.json`` the same things' words in that language, in its script and in English letters
as people type them. Words are compared by their search key, so "chaawal" counts as "chawal". A new
language adds its file; nothing else changes. Per-distributor words are in the backlog."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from common.search_keys import keys

WORDS_DIR = Path(__file__).with_name("words")


@cache
def things() -> dict[str, tuple[str, ...]]:
    """Each thing and all its words, in every language: ``{"rice": ("rice", "चावल", …)}``."""
    english: dict[str, list[str]] = json.loads((WORDS_DIR / "en.json").read_text("utf-8"))
    found = {thing: [thing, *words] for thing, words in english.items()}
    for path in sorted(WORDS_DIR.glob("*.json")):
        if path.stem != "en":
            for thing, words in json.loads(path.read_text("utf-8")).items():
                found[thing].extend(words)
    return {thing: tuple(dict.fromkeys(words)) for thing, words in found.items()}


@cache
def _by_key() -> dict[str, frozenset[str]]:
    """Each word's key and the keys of every word for the same thing (read once per process)."""
    table = things()
    words = [word for group in table.values() for word in group]
    key_of = dict(zip(words, keys(words), strict=True))
    found: dict[str, set[str]] = {}
    for group in table.values():
        group_keys = {key_of[word] for word in group}
        for word in group:
            found.setdefault(key_of[word], set()).update(group_keys)
    return {k: frozenset(v) for k, v in found.items()}


def other_words(word_key: str) -> frozenset[str]:
    """The keys of the other words for the thing a typed word names ("caval" → "rike", "tandul",
    …), none when it names none."""
    return _by_key().get(word_key, frozenset()) - {word_key}
