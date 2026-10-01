"""The supplier's email when a sent purchase order is cancelled (ADR-053, backend checkpoint)."""

from django.db import migrations

from apps.notifications.defaults import refresh_platform_templates


def forwards(apps, schema_editor):
    refresh_platform_templates(
        apps.get_model("notifications", "PlatformTemplate"), ["purchase_order.cancelled"]
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0015_purchase_order_texts")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
