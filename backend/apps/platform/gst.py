"""GSTIN checks that need the State table, shared by tenants and retailers (ADR-033)."""

from django.utils.translation import gettext as _

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
        return _("The first 2 digits (%(gstin)s) are not a GST state code.") % {"gstin": gstin[:2]}
    if not state.is_active:
        return _("State code %(code)s (%(name)s) is no longer used for new registrations.") % {
            "code": state.code,
            "name": state.name,
        }
    return None
