"""Every text the app shows, in one spreadsheet for translators (ADR-060 item 11).

manage.py texts_export                  # texts.xlsx
manage.py texts_export --out review.xlsx
"""

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand

from common import text_sheet


class Command(BaseCommand):
    help = "Write every screen, server and notification text to a spreadsheet for translators."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--out", default="texts.xlsx", help="Where to write the sheet.")

    def handle(self, *args: Any, out: str, **options: Any) -> None:
        path = Path(out)
        with path.open("wb") as stream:
            count = text_sheet.export(stream)
        self.stdout.write(f"{count} texts written to {path}.")
