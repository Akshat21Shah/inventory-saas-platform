"""Make permission codes and system roles in the database match apps/accounts/permissions.py."""

from typing import Any

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.permissions import sync_permissions


class Command(BaseCommand):
    help = "Sync permission codes and system roles from the code registry (idempotent)."

    def handle(self, *args: Any, **options: Any) -> None:
        with transaction.atomic():
            sync_permissions(apps)
        self.stdout.write(self.style.SUCCESS("permissions and system roles synced"))
