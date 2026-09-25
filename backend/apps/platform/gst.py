"""GSTIN checks that need the State table, shared by tenants and retailers (ADR-033)."""

from apps.platform.models import State
from apps.platform.validators import gstin_format_error


def gstin_problem(gstin: str) -> str | None:
    """The first problem with a normalized GSTIN (format, check character, state code in use),
    in plain words; None when it is valid."""
    problem = gstin_format_error(gstin)
    if problem is not None:
        return problem
    state = State.objects.filter(code=gstin[:2]).first()
    if state is None:
        return f"The first 2 digits ({gstin[:2]}) are not a GST state code."
    if not state.is_active:
        return f"State code {state.code} ({state.name}) is no longer used for new registrations."
    return None
