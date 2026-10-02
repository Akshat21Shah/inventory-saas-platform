"""'Suggest a better word' (ADR-060 item 14): staff and shops send a better translation from any
screen; the super admin's list collects them for the translation sheet."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.core.cache import cache
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.models import User
from apps.audit import services as audit
from apps.platform.models import TextSuggestion
from common import languages
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields, NotFound

PER_HOUR = 20  # suggestions per person per hour


class TooManySuggestions(DomainError):
    status_code = 429
    code = ErrorCode.RATE_LIMITED
    default_message = gettext_lazy(
        "Thank you! You've sent a lot of suggestions in the last hour. Try again a little later."
    )


@dataclass(frozen=True)
class SuggestionInput:
    language: str
    screen: str
    current_text: str
    suggestion: str


def _within_rate(user: User) -> bool:
    key = f"text-suggest:{user.pk}:{timezone.now():%Y%m%d%H}"
    cache.add(key, 0, 3600)
    try:
        count = cache.incr(key)
    except ValueError:  # expired between add and incr
        cache.set(key, 1, 3600)
        count = 1
    return count <= PER_HOUR


def suggest(user: User, tenant_id: UUID | None, data: SuggestionInput) -> TextSuggestion:
    if not languages.is_known(data.language):
        raise InvalidFields({"language": [_("Choose one of the languages offered.")]})
    if not data.suggestion.strip():
        raise InvalidFields({"suggestion": [_("Write the better word.")]})
    if not _within_rate(user):
        raise TooManySuggestions()
    made: TextSuggestion = TextSuggestion.objects.create(
        tenant_id=tenant_id,
        user=user,
        language=data.language,
        screen=data.screen.strip()[:300],
        current_text=data.current_text.strip()[:500],
        suggestion=data.suggestion.strip()[:500],
    )
    return made


def suggestions(status: str = "", language: str = "") -> QuerySet[TextSuggestion]:
    """The super admin's list, newest first."""
    qs = TextSuggestion.objects.select_related("tenant", "user", "resolved_by")
    if status:
        qs = qs.filter(status=status)
    if language:
        qs = qs.filter(language=language)
    return qs


def resolve(suggestion_id: UUID, status: str, *, by: User) -> TextSuggestion:
    """Mark a suggestion done (taken into the sheet) or dismissed, or back to new."""
    found: TextSuggestion | None = TextSuggestion.objects.filter(pk=suggestion_id).first()
    if found is None:
        raise NotFound()
    if status not in TextSuggestion.Status.values:
        raise InvalidFields({"status": [_("Choose new, done or dismissed.")]})
    before = found.status
    found.status = status
    done = status != TextSuggestion.Status.NEW
    found.resolved_by, found.resolved_at = (by, timezone.now()) if done else (None, None)
    found.save(update_fields=["status", "resolved_by", "resolved_at", "updated_at"])
    audit.record(
        "platform.text_suggestion_resolved",
        target=found,
        target_repr=f"{found.language}: {found.current_text[:60]}",
        changes={"status": [before, status]},
        tenant_id=None,
    )
    return found
