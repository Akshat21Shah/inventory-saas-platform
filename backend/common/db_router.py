"""Database routing for the two aliases of the same PostgreSQL database (ADR-002).

- Migrations run only on the default (owner) connection; the BYPASSRLS alias never migrates.
- Objects loaded through either alias may be related to each other: both aliases are the same
  physical database, only the connecting role differs.
"""

from typing import Any

_SAME_DATABASE = frozenset({"default", "platform"})


class PlatformAliasRouter:
    def allow_migrate(self, db: str, app_label: str, **hints: Any) -> bool | None:
        return db == "default"

    def allow_relation(self, obj1: Any, obj2: Any, **hints: Any) -> bool | None:
        if {obj1._state.db, obj2._state.db} <= _SAME_DATABASE:
            return True
        return None
