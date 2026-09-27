"""Print a test account's 2FA state as JSON: the server's current TOTP step and the last step it
accepted (replay protection). The E2E sign-in helper uses it to never reuse a step and to say why a
code was refused. Dev only: refuses unless DEBUG is on."""

import json
import time
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.accounts.mfa import TOTP_INTERVAL
from apps.accounts.models import User


class Command(BaseCommand):
    help = "Print the server TOTP step and the account's last accepted step (JSON)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--email", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("e2e_totp_state only runs with DEBUG=True")
        user = User.objects.filter(email=options["email"].strip().lower()).first()
        if user is None:
            raise CommandError("no such account")
        now = time.time()
        self.stdout.write(
            json.dumps(
                {
                    "server_time": now,
                    "server_step": int(now) // TOTP_INTERVAL,
                    "last_step": user.totp_last_step,
                }
            )
        )
