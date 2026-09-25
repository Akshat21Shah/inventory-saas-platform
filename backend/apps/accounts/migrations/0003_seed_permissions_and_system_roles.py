"""Seed permission codes and system roles from ``apps/accounts/permissions.py``."""

from django.db import migrations

from apps.accounts.permissions import sync_permissions


def forwards(apps, schema_editor):
    sync_permissions(apps)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_permissions_roles_memberships"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
