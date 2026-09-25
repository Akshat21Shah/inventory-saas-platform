"""The audited cross-tenant database path (ADR-002, ADR-026).

The ``platform`` alias connects with a BYPASSRLS role. Code must obtain the alias through
``platform_db(purpose)``, which logs every use with the acting user and purpose, so cross-tenant
reads stay explicit, few and reviewable. Grep for ``platform_db(`` to list every such path.
"""

import logging

from common.context import actor_var

PLATFORM_DB_ALIAS = "platform"

logger = logging.getLogger("platform_access")


def platform_db(purpose: str) -> str:
    actor = actor_var.get()
    logger.info(
        "platform alias used",
        extra={
            "purpose": purpose,
            "actor_id": str(actor.user_id) if actor else None,
            "actor_type": actor.actor_type if actor else "SYSTEM",
        },
    )
    return PLATFORM_DB_ALIAS
