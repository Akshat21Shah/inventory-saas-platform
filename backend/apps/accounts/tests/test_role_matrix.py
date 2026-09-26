"""PLAN 1.17: role permission matrix across every tenant endpoint that declares a permission.

Walks the URL conf. For each (endpoint, method) guarded by a tenant permission code, every system
role is tried: roles without the code must get 403; roles with it must not. New endpoints are
covered automatically.
"""

import re
import uuid

import pytest
from django.core.cache import cache
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.test import APIClient

from apps.accounts.permissions import SYSTEM_ROLES
from apps.accounts.tests.factories import make_staff_in
from apps.accounts.tokens import issue_tokens
from common.permissions import AllOf, AnyOf

pytestmark = pytest.mark.django_db

TENANT_ROLES = [r for r in SYSTEM_ROLES if not r.platform]
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


def _guarded_endpoints():
    rows = []

    def walk(patterns, prefix=""):
        for p in patterns:
            if isinstance(p, URLResolver):
                walk(p.url_patterns, prefix + str(p.pattern))
            elif isinstance(p, URLPattern):
                cls = getattr(p.callback, "view_class", None) or getattr(p.callback, "cls", None)
                route = prefix + str(p.pattern)
                if (
                    cls is None
                    or not route.startswith("api/v1/")
                    or route.startswith("api/v1/platform/")
                ):
                    continue
                per_method = getattr(cls, "required_permissions", None) or {}
                single = getattr(cls, "required_permission", None)
                for method in METHODS:
                    if not hasattr(cls, method.lower()):
                        continue
                    code = per_method.get(method) or single
                    safe_read = method == "GET" and "StaffReadsOrHasPermission" in {
                        c.__name__ for pc in cls.permission_classes for c in pc.__mro__
                    }
                    if code and not safe_read:
                        path = "/" + re.sub(r"<[^>]+>", str(uuid.uuid4()), route)
                        rows.append((path, method, code))

    walk(get_resolver().url_patterns)
    return rows


GUARDED = _guarded_endpoints()


def _allowed(code, permissions):
    if isinstance(code, AnyOf):
        return any(c in permissions for c in code)
    if isinstance(code, AllOf):
        return all(c in permissions for c in code)
    return code in permissions


def test_the_walk_found_the_guarded_endpoints():
    paths = {p for p, _, _ in GUARDED}
    assert "/api/v1/staff/" in paths
    assert "/api/v1/settings/bank-details/" in paths
    assert "/api/v1/audit-logs/" in paths


@pytest.mark.parametrize("role", TENANT_ROLES, ids=lambda r: r.code)
def test_each_role_is_allowed_exactly_what_its_permissions_say(tenant_a, role):
    cache.clear()
    user = make_staff_in(tenant_a, role.code)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, tenant_a.pk).access}")
    wrong = []
    for path, method, code in GUARDED:
        response = client.generic(
            method,
            path,
            "{}",
            content_type="application/json",
            HTTP_X_FORWARDED_HOST="alpha.localhost",
        )
        denied = response.status_code == 403
        if denied == _allowed(code, role.permissions):
            wrong.append(f"{method} {path} ({code}) -> {response.status_code}")
    assert wrong == []
