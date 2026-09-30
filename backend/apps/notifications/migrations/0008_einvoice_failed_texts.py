"""Texts for the new "IRN failed" staff message (Phase 7, ADR-049)."""

from django.db import migrations

from apps.notifications.defaults import refresh_platform_templates


def forwards(apps, schema_editor):
    refresh_platform_templates(
        apps.get_model("notifications", "PlatformTemplate"), ["einvoice.failed"]
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0007_whatsapp_approval")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
