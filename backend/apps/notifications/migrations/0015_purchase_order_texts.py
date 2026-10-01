"""The supplier's email when a purchase order is sent (ADR-053)."""

from django.db import migrations

from apps.notifications.defaults import refresh_platform_templates


def forwards(apps, schema_editor):
    refresh_platform_templates(
        apps.get_model("notifications", "PlatformTemplate"), ["purchase_order.sent"]
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0014_supplier_recipient")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
