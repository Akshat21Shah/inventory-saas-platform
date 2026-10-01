"""The super admin's search for people across distributors: the audited path (spec 5.17)."""

from apps.audit import services as audit
from apps.search.selectors import UserHit, normalize, users_matching


def search_users(text: str) -> list[UserHit]:
    """Every search is written to the platform's audit log with what was typed and how many
    people it found."""
    hits = users_matching(text)
    audit.record(
        "platform.users_searched",
        target_type="user",
        metadata={"query": normalize(text), "results": len(hits)},
        tenant_id=None,
    )
    return hits
