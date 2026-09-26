from django.db import migrations
from django.utils import timezone

import common.ids


def backfill(apps, schema_editor):
    """Existing (Phase 1) retailers get codes R-00001… in creation order and their distributor's
    state; the code counter continues after them."""
    Tenant = apps.get_model("platform", "Tenant")
    Retailer = apps.get_model("retailers", "Retailer")
    Sequence = apps.get_model("common", "Sequence")
    for tenant in Tenant.objects.all():
        retailers = list(Retailer.objects.filter(tenant_id=tenant.pk).order_by("created_at", "pk"))
        for number, retailer in enumerate(retailers, start=1):
            retailer.code = f"R-{number:05d}"
            retailer.state_id = retailer.state_id or tenant.state_id
            retailer.save(update_fields=["code", "state"])
        if retailers:
            counter, _ = Sequence.objects.get_or_create(
                tenant_id=tenant.pk, name="retailer_code", period="all",
                defaults={"id": common.ids.uuid7(), "next_value": 1},
            )
            counter.next_value = max(counter.next_value, len(retailers) + 1)
            counter.updated_at = timezone.now()
            counter.save(update_fields=["next_value", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("retailers", "0003_retailer_profile_fields"), ("common", "0001_initial")]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
