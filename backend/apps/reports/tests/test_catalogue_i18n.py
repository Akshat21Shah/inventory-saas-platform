"""Every report the server offers has its words in the web app's messages (CLAUDE.md §6: every
user-facing string through i18n): title, description, each column, each filter and each choice.
The report screens show these; the server's own labels are the fallback and the Excel headings."""

import json
from pathlib import Path

from django.conf import settings

from apps.reports.registry import REGISTRY, Group

MESSAGES = Path(settings.BASE_DIR).parent / "web" / "messages" / "en.json"


def test_every_report_has_its_words_in_the_web_messages():
    reports = json.loads(MESSAGES.read_text())["reports"]
    missing: list[str] = []
    for group in Group:
        if group.value not in reports["groups"]:
            missing.append(f"groups.{group.value}")
    for code, report in REGISTRY.items():
        entry = reports["catalogue"].get(code, {})
        missing += [f"{code}.{key}" for key in ("title", "description") if not entry.get(key)]
        missing += [
            f"{code}.columns.{c.key}"
            for c in report.columns
            if c.key not in entry.get("columns", {})
        ]
        for f in report.filters:
            if f.key not in reports["filters"]:
                missing.append(f"filters.{f.key}")
            missing += [
                f"choices.{f.key}.{choice}"
                for choice in f.choices
                if choice not in reports["choices"].get(f.key, {})
            ]
    assert missing == []
