"""Dev only: script the mock GST provider's next answers, e.g. ``manage.py mock_gsp portal_down
timeout`` (the worker shares them through the cache), or ``--reset`` to forget every IRN."""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.compliance.adapters.mock import SCRIPTABLE, MockGspClient


class Command(BaseCommand):
    help = "Script the mock GST provider's next answers (dev only)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "outcomes", nargs="*", help=f"any of: {', '.join(o.lower() for o in SCRIPTABLE)}"
        )
        parser.add_argument("--reset", action="store_true", help="forget scripts and IRNs")

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.ALLOW_MOCK_INTEGRATIONS:
            raise CommandError("The mock GST provider exists only in dev and test.")
        if options["reset"]:
            MockGspClient.reset()
        outcomes = [o.upper() for o in options["outcomes"]]
        try:
            MockGspClient.script(*outcomes)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Mock GSP: next answers {outcomes or 'as normal'}.")
