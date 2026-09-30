"""The "bill cancelled" email points at the bill (the new one when re-issued): Phase 7 backend
checkpoint, change 3."""

from django.db import migrations

from apps.notifications.defaults import refresh_platform_templates


def forwards(apps, schema_editor):
    refresh_platform_templates(
        apps.get_model("notifications", "PlatformTemplate"), ["invoice.cancelled"]
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0009_invoice_cancelled_texts")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
