"""Keep migrations on the default (owner) connection; the BYPASSRLS alias never migrates."""

from typing import Any


class PlatformAliasRouter:
    def allow_migrate(self, db: str, app_label: str, **hints: Any) -> bool | None:
        return db == "default"
