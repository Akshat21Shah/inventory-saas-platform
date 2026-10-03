"""The WhatsApp templates to submit to the provider for approval, per language (ADR-048,
ADR-060): the first batch (every shop message and the salesman's handover reminder), with the
provider's numbered parameters and a sample for each.

    manage.py whatsapp_submissions                   # every language, Markdown
    manage.py whatsapp_submissions --language hi     # one language
"""

import re
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import translation

from apps.notifications.catalog import (
    EVENTS,
    in_first_submission,
    texts_in,
    whatsapp_template_name,
)
from apps.notifications.defaults import languages
from apps.notifications.texts import SAMPLE, _sample_phrases

VARIABLE = re.compile(r"{{\s*(\w+)\s*}}")


def submissions(locale: str) -> list[dict[str, Any]]:
    with translation.override(locale):
        sample = {**SAMPLE, **{k: str(v) for k, v in _sample_phrases().items()}}
    rows = []
    for event, audiences in texts_in(locale).items():
        for audience, channels in audiences.items():
            text = channels.get("WHATSAPP")
            if text is None or event not in EVENTS or not in_first_submission(event, audience):
                continue
            names = list(dict.fromkeys(VARIABLE.findall(text.body)))
            numbered = text.body
            for index, name in enumerate(names, start=1):
                numbered = re.sub(r"{{\s*" + name + r"\s*}}", f"{{{{{index}}}}}", numbered)
            rows.append(
                {
                    "name": whatsapp_template_name(event, audience),
                    "language": locale,
                    "category": EVENTS[event].category,
                    "body": numbered,
                    "parameters": names,
                    "samples": [sample.get(n, "Sharma Traders") for n in names],
                }
            )
    return sorted(rows, key=lambda r: r["name"])


class Command(BaseCommand):
    help = "List the first-batch WhatsApp templates to submit for approval, per language."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--language", choices=languages(), default=None)

    def handle(self, *args: Any, language: str | None = None, **options: Any) -> None:
        for locale in [language] if language else languages():
            rows = submissions(locale)
            self.stdout.write(f"\n## {locale}: {len(rows)} templates\n")
            self.stdout.write("| Name | Category | Text | Parameters (sample) |")
            self.stdout.write("|---|---|---|---|")
            for row in rows:
                params = "; ".join(
                    f"{{{{{i}}}}} {name} ({sample})"
                    for i, (name, sample) in enumerate(
                        zip(row["parameters"], row["samples"], strict=True), start=1
                    )
                )
                body = row["body"].replace("|", "\\|").replace("\n", " ")
                self.stdout.write(f"| {row['name']} | {row['category']} | {body} | {params} |")
