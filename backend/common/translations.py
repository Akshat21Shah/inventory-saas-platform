"""Server message catalogs (ADR-060): ``locale/<code>/LC_MESSAGES/django.po`` per language, compiled
to ``django.mo`` (committed: the app reads them with Python's gettext at run time).

The messages are collected from the code itself (Python's ``ast``, so no GNU gettext is needed
anywhere): every call to ``_``, ``gettext``, ``gettext_lazy``, ``gettext_noop``, ``ngettext`` and
``pgettext`` (and their lazy forms) with literal text. ``manage.py messages`` brings each catalog
up to date (new messages added untranslated, removed ones dropped, translations kept) and
compiles it; ``manage.py messages --check`` and the tests fail when a catalog is out of date, a
message has no translation, or a translation's placeholders differ from the English.

Uses ``polib``; at run time the app reads the compiled files, and the super admin's translation
sheet (``common/text_sheet.py``) reads the catalogs too.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from common import languages

if TYPE_CHECKING:
    import polib

BACKEND = Path(__file__).resolve().parents[1]
LOCALE = BACKEND / "locale"
SOURCES = ("apps", "common", "config")
SKIP_PARTS = {"tests", "testing", "migrations", "management", "__pycache__"}
REVIEW_NOTE = "Machine-drafted; needs a native speaker's review (pre-production item 42)."

# keyword → (index of the context or None, index of the message, index of the plural or None)
KEYWORDS: dict[str, tuple[int | None, int, int | None]] = {
    "_": (None, 0, None),
    "gettext": (None, 0, None),
    "gettext_lazy": (None, 0, None),
    "gettext_noop": (None, 0, None),
    "ngettext": (None, 0, 1),
    "ngettext_lazy": (None, 0, 1),
    "pgettext": (0, 1, None),
    "pgettext_lazy": (0, 1, None),
}
PERCENT = re.compile(r"%\((\w+)\)[sdfr]|%%")
BRACES = re.compile(r"(?<!\{)\{(\w*)[^{}]*\}(?!\})")


@dataclass
class Message:
    msgid: str
    plural: str = ""
    context: str = ""
    where: set[str] = field(default_factory=set)

    @property
    def key(self) -> tuple[str, str]:
        return (self.context, self.msgid)


def _source_files() -> Iterator[Path]:
    for root in SOURCES:
        for path in sorted((BACKEND / root).rglob("*.py")):
            relative = path.relative_to(BACKEND)
            if not SKIP_PARTS & set(relative.parts) and not path.name.startswith("demo"):
                yield path


def _text(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def extract() -> dict[tuple[str, str], Message]:
    """Every translatable message in the backend's code, by (context, msgid)."""
    found: dict[tuple[str, str], Message] = {}
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name not in KEYWORDS:
                continue
            context_at, message_at, plural_at = KEYWORDS[name]
            if len(node.args) <= message_at:
                continue
            msgid = _text(node.args[message_at])
            if not msgid:
                continue
            context = _text(node.args[context_at]) if context_at is not None else ""
            plural = _text(node.args[plural_at]) if plural_at is not None else ""
            message = Message(msgid, plural or "", context or "")
            message = found.setdefault(message.key, message)
            # The file only, no line number: a catalog changes when messages do, not when
            # unrelated code above them moves.
            message.where.add(str(path.relative_to(BACKEND)))
    return found


def po_path(code: str) -> Path:
    return LOCALE / code / "LC_MESSAGES" / "django.po"


def translated_languages() -> list[languages.Language]:
    """The languages with server catalogs: all but English (the messages are written in it)."""
    return [language for language in languages.all_languages() if language.code != "en"]


def _load(code: str) -> polib.POFile:
    import polib

    path = po_path(code)
    if path.exists():
        return polib.pofile(str(path), wrapwidth=0)
    catalog = polib.POFile(wrapwidth=0)
    return catalog


def _header(catalog: polib.POFile, language: languages.Language) -> None:
    catalog.header = f"{language.name} server messages (ADR-060). {REVIEW_NOTE}"
    catalog.metadata = {
        "Project-Id-Version": "inventory-platform",
        "Language": language.code,
        "MIME-Version": "1.0",
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
        "Plural-Forms": language.plural_forms,
    }


def updated(language: languages.Language) -> polib.POFile:
    """The language's catalog brought up to date with the code (not written)."""
    import polib

    messages = extract()
    old = _load(language.code)
    kept = {(entry.msgctxt or "", entry.msgid): entry for entry in old if not entry.obsolete}
    catalog = polib.POFile(wrapwidth=0)
    _header(catalog, language)
    nplurals = int(re.search(r"nplurals=(\d+)", language.plural_forms).group(1))  # type: ignore[union-attr]
    for key in sorted(messages, key=lambda k: (k[1].lower(), k[0])):
        message = messages[key]
        previous = kept.get(key)
        entry = polib.POEntry(
            msgid=message.msgid,
            msgctxt=message.context or None,
            occurrences=[(where, "") for where in sorted(message.where)][:3],
        )
        if message.plural:
            entry.msgid_plural = message.plural
            entry.msgstr_plural = (
                dict(previous.msgstr_plural)
                if previous is not None and previous.msgstr_plural
                else dict.fromkeys(range(nplurals), "")
            )
        else:
            entry.msgstr = previous.msgstr if previous is not None else ""
        if "%(" in message.msgid or "%%" in message.msgid:
            entry.flags.append("python-format")
        catalog.append(entry)
    return catalog


def compiled(catalog: polib.POFile) -> bytes:
    """The .mo bytes for a catalog (deterministic)."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".mo") as handle:
        catalog.save_as_mofile(handle.name)
        return Path(handle.name).read_bytes()


def po_text(catalog: polib.POFile) -> str:
    return str(catalog) + "\n" if not str(catalog).endswith("\n") else str(catalog)


def placeholders(text: str) -> list[str]:
    return sorted(PERCENT.findall(text)) + sorted(BRACES.findall(text))


def problems(language: languages.Language) -> list[str]:
    """What is wrong with a language's catalog as committed: out of date with the code, a
    message without a translation, placeholders that differ, a stale compiled file."""
    found: list[str] = []
    path = po_path(language.code)
    if not path.exists():
        return [f"{language.code}: no catalog at {path.relative_to(BACKEND)}"]
    current = updated(language)
    if po_text(current) != path.read_text(encoding="utf-8"):
        found.append(f"{language.code}: django.po is out of date: run `make messages`")
    for entry in current:
        texts = list(entry.msgstr_plural.values()) if entry.msgid_plural else [entry.msgstr]
        if not all(texts):
            found.append(f"{language.code}: no translation for {entry.msgid!r}")
            continue
        for text in texts:
            if placeholders(text) != placeholders(entry.msgid):
                found.append(f"{language.code}: placeholders differ in {entry.msgid!r} → {text!r}")
    mo = path.with_suffix(".mo")
    if not mo.exists() or mo.read_bytes() != compiled(_load(language.code)):
        found.append(f"{language.code}: django.mo is out of date: run `make messages`")
    return found


def write(language: languages.Language) -> polib.POFile:
    catalog = updated(language)
    path = po_path(language.code)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(po_text(catalog), encoding="utf-8")
    path.with_suffix(".mo").write_bytes(compiled(_load(language.code)))
    return catalog


def untranslated(catalog: polib.POFile) -> list[str]:
    return [
        entry.msgid
        for entry in catalog
        if not (all(entry.msgstr_plural.values()) if entry.msgid_plural else entry.msgstr)
    ]
