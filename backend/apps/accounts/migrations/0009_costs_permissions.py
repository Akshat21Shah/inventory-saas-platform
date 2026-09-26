"""ADR-042: costs.view and costs.manage, separate from pricing (roles re-synced from the registry)."""

from django.db import migrations

from apps.accounts.permissions import sync_permissions


def forwards(apps, schema_editor):
    sync_permissions(apps)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0008_impersonation")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
