"""ADR-053 item 9: purchasing.view (owner, manager, warehouse, accounts) and purchasing.manage
(owner, manager); roles re-synced from the registry."""

from django.db import migrations

from apps.accounts.permissions import sync_permissions


def forwards(apps, schema_editor):
    sync_permissions(apps)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0010_payments_collect")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
