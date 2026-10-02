"""Bring the server message catalogs up to date with the code and compile them (ADR-060).

manage.py messages          # update locale/<code>/LC_MESSAGES/django.po and .mo
manage.py messages --check  # fail if anything is out of date or untranslated (CI, tests)
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from common import translations


class Command(BaseCommand):
    help = "Update and compile the server message catalogs (locale/*/LC_MESSAGES/django.po)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--check", action="store_true", help="Change nothing; fail if stale.")

    def handle(self, *args: Any, check: bool = False, **options: Any) -> None:
        if check:
            found = [
                p
                for lang in translations.translated_languages()
                for p in translations.problems(lang)
            ]
            if found:
                raise CommandError("\n".join(found[:50]) + f"\n({len(found)} problems)")
            self.stdout.write("Message catalogs are up to date.")
            return
        for language in translations.translated_languages():
            catalog = translations.write(language)
            missing = translations.untranslated(catalog)
            self.stdout.write(
                f"{language.code}: {len(catalog)} messages, {len(missing)} without a translation"
            )
