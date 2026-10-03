"""The platform's default texts in Hindi and Marathi (ADR-060): one row per event, audience,
channel and language, so WhatsApp templates in each language get their own approval."""

from django.db import migrations

from apps.notifications.defaults import sync_platform_templates


def forwards(apps, schema_editor):
    sync_platform_templates(apps.get_model("notifications", "PlatformTemplate"))


class Migration(migrations.Migration):
    dependencies = [("notifications", "0016_purchase_order_cancelled_texts")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
