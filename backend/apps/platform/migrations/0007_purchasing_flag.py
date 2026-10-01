"""ADR-053 item 9: the ``purchasing`` flag (off by default)."""

from django.db import migrations

from apps.platform.reference_data import seed_reference_data


def forwards(apps, schema_editor):
    seed_reference_data(apps)


class Migration(migrations.Migration):
    dependencies = [("platform", "0006_stock_planning_flag")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
