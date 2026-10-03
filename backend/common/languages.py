"""The app's languages (ADR-060): a manifest (``languages.json``) lists them, and each language's
files (screens, server messages, notification texts, search words) carry its words. Adding a
language is a manifest line and those files, never code.

Which languages a person may choose is a platform decision (ADR-060 item 12): the super admin
enables languages for everyone (⚙ ``platform.languages_enabled``); until a language is reviewed
it is available only for testing, to super admins and to the distributors listed in
⚙ ``platform.language_test_tenants``."""

from __future__ import annotations

import json
import re
from contextlib import AbstractContextManager
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any
from uuid import UUID

from django.utils.translation import gettext as _

from common.numbers import fill

MANIFEST = Path(__file__).with_name("languages.json")
CODE = re.compile(r"^[a-z]{2,3}$")


@dataclass(frozen=True)
class Language:
    code: str
    name: str  # in English
    native: str  # in its own script
    script: str
    pdf_font: str
    plural_forms: str  # gettext's Plural-Forms header for its server messages


@cache
def _manifest() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return data


@cache
def all_languages() -> tuple[Language, ...]:
    return tuple(Language(**row) for row in _manifest()["languages"])


DEFAULT = "en"


def codes() -> tuple[str, ...]:
    return tuple(language.code for language in all_languages())


def get(code: str) -> Language | None:
    return next((language for language in all_languages() if language.code == code), None)


def is_known(code: str) -> bool:
    return get(code) is not None


def _listed(value: Any) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def enabled() -> tuple[str, ...]:
    """Languages everyone may choose (English always), in the manifest's order."""
    from apps.platform.selectors import get_platform_setting

    chosen = set(_listed(get_platform_setting("platform.languages_enabled"))) | {DEFAULT}
    return tuple(code for code in codes() if code in chosen)


def test_tenant_slugs() -> set[str]:
    from apps.platform.selectors import get_platform_setting

    return set(_listed(get_platform_setting("platform.language_test_tenants")))


def available(*, platform_user: bool = False, tenant_slug: str | None = None) -> tuple[str, ...]:
    """What a person may choose: every language for super admins and at test distributors,
    else the enabled ones."""
    if platform_user or (tenant_slug and tenant_slug in test_tenant_slugs()):
        return codes()
    return enabled()


def available_for_tenant(tenant_id: UUID | None) -> tuple[str, ...]:
    """The languages a distributor's staff and shops may use (also its messages and documents)."""
    if tenant_id is None:
        return enabled()
    from apps.platform.models import Tenant

    slug = Tenant.objects.filter(pk=tenant_id).values_list("slug", flat=True).first()
    return available(tenant_slug=slug)


def effective(code: str | None, allowed: tuple[str, ...]) -> str:
    """``code`` if it may be used, else English."""
    return code if code and code in allowed else DEFAULT


def shop_language(retailer: Any) -> str:
    """A shop's language: its own, else its distributor's default for shops (both only if the
    distributor may use them), else English."""
    from apps.platform.selectors import get_setting

    allowed = available_for_tenant(retailer.tenant_id)
    own = (retailer.preferred_language or "").strip()
    default = str(get_setting("retailers.default_language", retailer.tenant_id) or DEFAULT)
    return effective(own or default, allowed)


def user_language(user: Any, tenant_id: UUID | None) -> str:
    """A person's language (staff, super admin or a shop's login)."""
    platform_user = getattr(user, "user_type", "") == "PLATFORM"
    if platform_user:
        return effective(user.preferred_language, codes())
    return effective(user.preferred_language, available_for_tenant(tenant_id))


def by_any_name() -> dict[str, str]:
    """Code by code, English name or native name (lower case): "hindi", "हिन्दी", "hi" → "hi"."""
    names: dict[str, str] = {}
    for language in all_languages():
        for key in (language.code, language.name, language.native):
            names[key.lower()] = language.code
    return names


def validate_code(value: str, *, allow_blank: bool = False) -> str:
    """For serializers: a known language code (or blank when allowed)."""
    from rest_framework import serializers

    value = (value or "").strip()
    if not value and allow_blank:
        return ""
    if not is_known(value):
        raise serializers.ValidationError(
            fill(_("Choose one of: %(codes)s."), {"codes": ", ".join(codes())})
        )
    return value


def speaking(user: Any, tenant_id: UUID | None) -> AbstractContextManager[None]:
    """Background work for a person (an import, a report) in their language: what it stores to
    show them later (messages, notes) is written in it."""
    from django.utils import translation

    return translation.override(user_language(user, tenant_id) if user is not None else DEFAULT)
