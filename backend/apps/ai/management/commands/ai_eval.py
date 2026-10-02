"""Run the assistant's evaluation set (ADR-059 item 7) on a distributor's own data, as one of its
staff, with the configured provider or ``--provider``, and the model from the platform setting
or ``--model``. Each question is asked and logged like any other (and uses AI units); the report
is then run directly to check the answer's figures. Prints accuracy, and units, estimated cost
and time per question, priced at the model's price settings (ADR-059 item 8).

    python manage.py ai_eval                       # sharma, its owner, the mock
    python manage.py ai_eval --provider anthropic --model claude-sonnet-5-5          # item 40
    python manage.py ai_eval --provider anthropic --model claude-haiku-4-5-20251001  # item 40
"""

from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.test import override_settings

from apps.accounts.models import User
from apps.ai import pricing, services
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
        parser.add_argument(
            "--model",
            default="",
            choices=["", *pricing.MODEL_PRICES],
            help="The model to ask (default: the platform setting).",
        )

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
        model = options["model"] or None
        prices = pricing.prices(model)
        right, units, cost, seconds = 0, 0, Decimal(0), 0.0
        with override_settings(**overrides), tenant_transaction(tenant.pk):
            product = Product.objects.filter(deleted_at__isnull=True).order_by("name").first()
            for case in CASES:
                outcome = run_case(
                    case, user, product=product.name if product else "salt", model=model
                )
                each = prices.cost("ASSISTANT", outcome.units_in, outcome.units_out)
                right += outcome.ok
                units += outcome.units_in + outcome.units_out
                cost += each
                seconds += outcome.seconds
                mark = "ok  " if outcome.ok else "FAIL"
                self.stdout.write(
                    f"{mark} {outcome.question}  [{outcome.units_in}+{outcome.units_out} units, "
                    f"₹{pricing.rupees(each)}, {outcome.seconds:.1f} s]"
                )
                self.stdout.write(f"     {outcome.answer[:300]!r}")
                for problem in outcome.problems:
                    self.stdout.write(f"     - {problem}")
        n = len(CASES)
        self.stdout.write(
            f"\n{prices.model}: {right}/{n} right ({right * 100 // n}%); per question on average "
            f"{units // n} units, ₹{pricing.rupees(cost / n)}, {seconds / n:.1f} s "
            f"(prices: platform settings; answered by {outcome.model or 'the provider'})"
        )
        if right < n:
            raise CommandError(f"{n - right} of {n} questions answered wrongly")
        self.stdout.write(self.style.SUCCESS(f"all {n} questions answered correctly"))
