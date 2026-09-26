"""Print the ids of seeded Sharma records as JSON, so the responsive E2E check can open detail
pages (a product, a shop, a price list, a discount rule, goods receipts, an adjustment). Dev only:
refuses unless DEBUG is on."""

import json
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import Product
from apps.dataio.models import ImportJob
from apps.inventory.models import StockAdjustment, StockInward
from apps.platform.models import Tenant
from apps.pricing.models import DiscountRule, PriceList
from apps.retailers.models import Retailer
from common.tenancy import tenant_transaction


def _first(qs: Any) -> str | None:
    pk = qs.order_by("created_at").values_list("pk", flat=True).first()
    return str(pk) if pk else None


class Command(BaseCommand):
    help = "Print seeded record ids (JSON) for the responsive E2E check."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("e2e_ids only runs with DEBUG=True")
        tenant = Tenant.objects.get(slug="sharma")
        with tenant_transaction(tenant.pk):
            job = ImportJob.objects.order_by("-created_at").first()
            ids = {
                "tenant": str(tenant.pk),
                "retailer": str(Retailer.objects.order_by("code").values_list("pk", flat=True)[0]),
                "product": str(
                    Product.objects.filter(deleted_at__isnull=True)
                    .order_by("code")
                    .values_list("pk", flat=True)[0]
                ),
                "price_list": str(
                    PriceList.objects.order_by("name").values_list("pk", flat=True)[0]
                ),
                "rule": str(DiscountRule.objects.order_by("name").values_list("pk", flat=True)[0]),
                "import_job": str(job.pk) if job else None,
                "receipt": _first(StockInward.objects.filter(status="POSTED")),
                "draft_receipt": _first(StockInward.objects.filter(status="DRAFT")),
                "adjustment": _first(StockAdjustment.objects.all()),
            }
        self.stdout.write(json.dumps(ids))
