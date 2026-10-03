"""The Android app's versions and settings (ADR-061 item 6).

Every request from the app carries its version (``X-App-Version: 1.2.0``). Below the super admin's
minimum (⚙ ``platform.app_min_version``) the API answers ``426 APP_UPDATE_REQUIRED`` and the app
shows its "Update the app" screen. The web never sends the header, so it is never affected.
"""

import re
from collections.abc import Callable
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.translation import gettext as _

from apps.platform.selectors import get_platform_setting
from common.error_codes import ErrorCode
from common.exceptions import error_body

VERSION_HEADER = "HTTP_X_APP_VERSION"
CONFIG_PATH = "/api/v1/app/config/"  # always answered: it tells an old app what to do
_VERSION = re.compile(r"(\d{1,3})\.(\d{1,3})\.(\d{1,3})")


def parse_version(raw: str | None) -> tuple[int, int, int] | None:
    match = _VERSION.fullmatch((raw or "").strip())
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def app_config() -> dict[str, Any]:
    return {
        "min_version": get_platform_setting("platform.app_min_version"),
        "latest_version": get_platform_setting("platform.app_latest_version"),
        "privacy_policy_url": get_platform_setting("platform.privacy_policy_url"),
    }


def update_required(raw_version: str) -> str | None:
    """The minimum version when ``raw_version`` is below it (or unreadable), else None."""
    minimum: str = get_platform_setting("platform.app_min_version")
    floor = parse_version(minimum) or (0, 0, 0)
    version = parse_version(raw_version)
    if version is None or version < floor:
        return minimum
    return None


class AppVersionMiddleware:
    """Refuse API requests from app versions below the minimum, before any view runs."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        raw = request.META.get(VERSION_HEADER)
        if raw is not None and request.path.startswith("/api/") and request.path != CONFIG_PATH:
            minimum = update_required(raw)
            if minimum is not None:
                body = error_body(
                    ErrorCode.APP_UPDATE_REQUIRED,
                    _("This version of the app is too old. Update it to continue."),
                    {"min_version": minimum},
                )
                return JsonResponse(body, status=426)
        return self.get_response(request)
