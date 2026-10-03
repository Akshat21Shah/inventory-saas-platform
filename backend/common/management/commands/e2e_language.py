"""Set the language the E2E test accounts see (ADR-060): the responsive check runs once per
language and puts English back after. Staff and super admins by email (their own language),
shop logins by mobile (their shop's language). Dev only: refuses unless DEBUG is on.

manage.py e2e_language hi --email owner@sharma.example.com --phone 9876500001
manage.py e2e_language en --email …        # English (shops: back to their distributor's default)"""

from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.accounts.models import User
from apps.retailers.models import Retailer, RetailerUser
from common import languages
from common.phone import normalize_indian_mobile
from common.tenancy import tenant_transaction


class Command(BaseCommand):
    help = "Set the language the given test accounts (and test shops) see."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("language", help="A language code, e.g. hi; en for English.")
        parser.add_argument("--email", action="append", default=[], help="repeatable")
        parser.add_argument("--phone", action="append", default=[], help="repeatable")

    def handle(self, *args: Any, language: str, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("e2e_language only runs with DEBUG=True")
        if not languages.is_known(language):
            raise CommandError(f"unknown language {language!r}")
        # A shop on English follows its distributor's default, as a new shop does.
        shop_saved = "" if language == languages.DEFAULT else language
        emails = [email.strip().lower() for email in options["email"]]
        changed = User.objects.filter(email__in=emails).update(preferred_language=language)
        try:
            phones = [normalize_indian_mobile(phone) for phone in options["phone"]]
        except ValidationError as exc:
            raise CommandError(str(exc.messages[0])) from exc
        for user in User.objects.filter(phone__in=phones, tenant__isnull=False):
            User.objects.filter(pk=user.pk).update(preferred_language=language)
            assert user.tenant_id is not None
            with tenant_transaction(user.tenant_id):
                shops = RetailerUser.objects.filter(user=user).values_list("retailer_id")
                changed += Retailer.objects.filter(pk__in=shops).update(
                    preferred_language=shop_saved
                )
        self.stdout.write(f"{changed} accounts and shops now see {language}.")
