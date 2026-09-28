"""Platform default templates (English) from the catalogue (ADR-048)."""

from django.db import migrations

from apps.notifications.defaults import sync_platform_templates


def forwards(apps, schema_editor):
    sync_platform_templates(apps.get_model("notifications", "PlatformTemplate"))


class Migration(migrations.Migration):
    dependencies = [("notifications", "0001_notifications")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
