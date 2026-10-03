"""Check a translator's spreadsheet and write it back (ADR-060 item 11).

manage.py texts_import review.xlsx           # check only: problems and what would change
manage.py texts_import review.xlsx --apply   # write the files (then run the tests and commit)

Checks placeholders, plural forms and SMS and WhatsApp lengths; a sheet with errors writes
nothing. Changed notification texts come with a data migration for the platform's copies."""

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from common import text_sheet


class Command(BaseCommand):
    help = "Check a translator's spreadsheet; with --apply, write it into the text files."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("sheet", help="The .xlsx file a translator sent back.")
        parser.add_argument("--apply", action="store_true", help="Write the changes.")

    def handle(self, *args: Any, sheet: str, apply: bool = False, **options: Any) -> None:
        outcome = text_sheet.read(Path(sheet))
        for warning in outcome.warnings:
            self.stdout.write(f"warning: {warning}")
        reviewed = sum(len(keys) for keys in outcome.reviewed.values())
        self.stdout.write(
            f"{outcome.rows_read} rows read: {len(outcome.changes)} texts changed, "
            f"{reviewed} marked reviewed."
        )
        if outcome.errors:
            raise CommandError("\n".join(outcome.errors) + f"\n({len(outcome.errors)} errors)")
        if not apply:
            self.stdout.write("Nothing written (add --apply to write).")
            return
        for path in text_sheet.apply(outcome):
            self.stdout.write(f"wrote {path}")
        self.stdout.write("Now run `make messages` checks and the tests, then commit.")
