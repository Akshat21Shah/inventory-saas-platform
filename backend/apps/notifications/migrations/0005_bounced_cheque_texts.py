"""The bounced-cheque message names the cheque's date and the shop's new balance (Phase 6
backend checkpoint, decision 4)."""

from django.db import migrations

from apps.notifications.defaults import refresh_platform_templates


def forwards(apps, schema_editor):
    refresh_platform_templates(
        apps.get_model("notifications", "PlatformTemplate"), ["payment.bounced"]
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0004_reminder_texts")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
