"""Clear rate-limit counters, lockouts and 2FA replay state for the E2E test accounts, so the
end-to-end suites can run any number of times in a row. Dev only: refuses unless DEBUG is on.

It never waits long behind another session's lock on these accounts (a stuck request, a
debugger): after ``LOCK_TIMEOUT`` it fails, and the E2E helper runs it once more."""

from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import OperationalError, connection, transaction

from apps.accounts.models import User
from common import ratelimit
from common.phone import normalize_indian_mobile

LOCK_TIMEOUT = "10s"


class Command(BaseCommand):
    help = "Reset rate limits, lockouts and 2FA replay state for the given test accounts."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--email", action="append", default=[], help="repeatable")
        parser.add_argument("--phone", action="append", default=[], help="repeatable")

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("reset_e2e_limits only runs with DEBUG=True")
        emails = [email.strip().lower() for email in options["email"]]
        try:
            phones = [normalize_indian_mobile(phone) for phone in options["phone"]]
        except ValidationError as exc:
            raise CommandError(str(exc.messages[0])) from exc
        users = User.objects.filter(email__in=emails)
        user_ids = [str(pk) for pk in users.values_list("pk", flat=True)]
        # Per-IP counters too: every E2E request comes from the same address.
        removed = ratelimit.clear([*emails, *phones, *user_ids], ip_buckets=True)
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('lock_timeout', %s, true)", [LOCK_TIMEOUT])
                unlocked = users.update(
                    failed_login_count=0, locked_until=None, totp_last_step=None
                )
        except OperationalError as exc:
            raise CommandError(
                f"the test accounts are locked by another session (waited {LOCK_TIMEOUT}); "
                "try again"
            ) from exc
        self.stdout.write(f"cleared {removed} rate-limit counters; reset {unlocked} accounts")
