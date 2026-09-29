"""Payment reminder texts cover bills due soon as well as overdue ones (ADR-048 item 10)."""

from django.db import migrations

from apps.notifications.defaults import refresh_platform_templates


def forwards(apps, schema_editor):
    refresh_platform_templates(
        apps.get_model("notifications", "PlatformTemplate"), ["payment.reminder"]
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0003_sending_status")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
