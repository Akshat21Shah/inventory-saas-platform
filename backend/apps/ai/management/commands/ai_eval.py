"""Run the assistant's evaluation set (ADR-059 item 7) on a distributor's own data, as one of its
staff, with the configured provider or ``--provider``. Each question is asked and logged like any
other (and uses AI units); the report is then run directly to check the answer's figures.

    python manage.py ai_eval                       # sharma, its owner, the mock
    python manage.py ai_eval --provider anthropic  # pre-production item 40
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.test import override_settings

from apps.accounts.models import User
from apps.ai import services
from apps.ai.assistant.evaluation import CASES, run_case
from apps.catalog.models import Product
from apps.platform.models import Tenant
from common.tenancy import tenant_transaction


class Command(BaseCommand):
    help = "Ask the assistant's evaluation questions on a distributor's data and check the answers."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", default="sharma")
        parser.add_argument("--email", default="", help="Default: owner@<tenant>.example.com")
        parser.add_argument("--provider", default="", help="mock or anthropic (default: settings)")

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = Tenant.objects.filter(slug=options["tenant"]).first()
        if tenant is None:
            raise CommandError(f"no distributor {options['tenant']}")
        email = options["email"] or f"owner@{tenant.slug}.example.com"
        user = User.objects.filter(email=email).first()
        if user is None:
            raise CommandError(f"no user {email}")
        if not services.enabled(tenant.pk):
            raise CommandError(f"the ai module is off for {tenant.slug}")
        overrides = {"AI_ASSISTANT_PROVIDER": options["provider"]} if options["provider"] else {}
        failed = 0
        with override_settings(**overrides), tenant_transaction(tenant.pk):
            product = Product.objects.filter(deleted_at__isnull=True).order_by("name").first()
            for case in CASES:
                outcome = run_case(case, user, product=product.name if product else "salt")
                mark = "ok  " if outcome.ok else "FAIL"
                failed += not outcome.ok
                self.stdout.write(f"{mark} {outcome.question}")
                self.stdout.write(f"     {outcome.answer[:300]!r}")
                for problem in outcome.problems:
                    self.stdout.write(f"     - {problem}")
        if failed:
            raise CommandError(f"{failed} of {len(CASES)} questions answered wrongly")
        self.stdout.write(self.style.SUCCESS(f"all {len(CASES)} questions answered correctly"))
