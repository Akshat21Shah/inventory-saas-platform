"""Re-encrypt every EncryptedTextField value with the current primary key (ADR-031).

Rotation: prepend the new key to FIELD_ENCRYPTION_KEYS, deploy, run this command (as the owner DB
role, like migrations), then remove the old key.
"""

from typing import Any

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from common.crypto import EncryptedTextField


class Command(BaseCommand):
    help = "Re-encrypt all encrypted fields with the current primary key."

    def handle(self, *args: Any, **options: Any) -> None:
        total = 0
        for model in apps.get_models():
            fields = [f for f in model._meta.concrete_fields if isinstance(f, EncryptedTextField)]
            if not fields:
                continue
            names = [f.attname for f in fields]
            count = 0
            # _base_manager is unfiltered: rotation is a platform maintenance task across tenants.
            with transaction.atomic():
                for obj in model._base_manager.only("pk", *names).iterator():
                    values = {name: getattr(obj, name) for name in names}
                    model._base_manager.filter(pk=obj.pk).update(**values)
                    count += 1
            self.stdout.write(f"{model._meta.label}: {count} rows re-encrypted")
            total += count
        self.stdout.write(self.style.SUCCESS(f"rotation complete ({total} rows)"))
