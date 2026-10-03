"""Print a fresh link to the Android app's browser payment page (ADR-061 item 9) for the seeded
shop's open checkout, starting a ₹1 checkout when it has none, so the responsive E2E check can open
the page. Each link works once. Dev only: refuses unless DEBUG is on."""

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.payments import browser, online
from apps.payments.models import PaymentIntent
from apps.platform.models import Tenant
from apps.retailers.models import Retailer
from common.tenancy import tenant_transaction

PHONE = "+919876500001"


class Command(BaseCommand):
    help = "Print a one-time link to the app's browser payment page (JSON) for E2E checks."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("e2e_pay_link only runs with DEBUG=True")
        tenant = Tenant.objects.get(slug="sharma")
        with tenant_transaction(tenant.pk):
            shop = Retailer.objects.get(mobile=PHONE)
            user = User.objects.get(tenant=tenant, phone=PHONE)
            intent = (
                PaymentIntent.objects.filter(
                    retailer=shop,
                    status__in=PaymentIntent.ACTIVE,
                    expires_at__gt=timezone.now() + timedelta(minutes=5),
                )
                .order_by("-created_at")
                .first()
            )
            if intent is None:
                intent = online.start_checkout(
                    shop, purpose="CUSTOM", invoice_id=None, amount=Decimal("1.00"), by=user
                )
            url, _ = browser.browser_link(intent, user)
        self.stdout.write(json.dumps({"url": url}))
