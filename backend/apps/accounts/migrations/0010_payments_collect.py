"""ADR-046 item 6: payments.collect for Sales (roles re-synced from the registry)."""

from django.db import migrations

from apps.accounts.permissions import sync_permissions


def forwards(apps, schema_editor):
    sync_permissions(apps)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0009_costs_permissions")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
