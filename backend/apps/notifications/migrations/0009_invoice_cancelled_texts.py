"""Texts for the shop's "bill cancelled" message (Phase 7, ADR-049 item 7)."""

from django.db import migrations

from apps.notifications.defaults import refresh_platform_templates


def forwards(apps, schema_editor):
    refresh_platform_templates(
        apps.get_model("notifications", "PlatformTemplate"), ["invoice.cancelled"]
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0008_einvoice_failed_texts")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
