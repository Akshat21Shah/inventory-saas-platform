"""The texts of the "Report ready" and "Report could not be made" system messages (ADR-050)."""

from django.db import migrations

from apps.notifications.defaults import refresh_platform_templates


def forwards(apps, schema_editor):
    refresh_platform_templates(
        apps.get_model("notifications", "PlatformTemplate"), ["report.ready", "report.failed"]
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0012_alter_notificationrule_recipient")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
