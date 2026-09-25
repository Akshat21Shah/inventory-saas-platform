from typing import Any

import pytest
from django.http import HttpResponse
from django.test import RequestFactory
from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.tokens import AccessToken

from common.authentication import (
    IMPERSONATION_SESSION_CLAIM,
    IMPERSONATOR_CLAIM,
    TENANT_CLAIM,
    TenantJWTAuthentication,
)
from common.context import actor_var, request_meta_var, tenant_id_var, user_id_var
from common.middleware import RequestContextMiddleware
from common.net import TrustedProxyMiddleware, client_ip


@pytest.mark.parametrize(
    ("trusted", "xff", "remote", "expected"),
    [
        ([], "198.51.100.1", "10.0.0.2", "10.0.0.2"),  # no trusted proxy: header ignored
        (["10.0.0.2"], "", "10.0.0.2", "10.0.0.2"),  # no header: socket address
        (["10.0.0.2"], "198.51.100.1", "10.0.0.2", "198.51.100.1"),
        (["10.0.0.0/8"], "198.51.100.1, 10.0.0.9", "10.0.0.2", "198.51.100.1"),  # skip our proxies
        (["10.0.0.2"], "198.51.100.1", "203.0.113.9", "203.0.113.9"),  # peer not trusted
        (["10.0.0.2"], "not-an-ip", "10.0.0.2", "10.0.0.2"),
        (["10.0.0.2"], "2001:db8::1", "10.0.0.2", "2001:db8::1"),
        (["127.0.0.1"], "198.51.100.1", "::ffff:127.0.0.1", "198.51.100.1"),  # mapped IPv4
    ],
)
def test_client_ip(settings, trusted, xff, remote, expected):
    settings.TRUSTED_PROXIES = trusted
    request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR=xff, REMOTE_ADDR=remote)
    assert client_ip(request) == expected


def test_forwarded_headers_from_untrusted_peers_are_discarded(settings):
    settings.TRUSTED_PROXIES = ["10.0.0.2"]
    seen: dict[str, str | None] = {}

    def view(request):
        seen.update(
            xff=request.META.get("HTTP_X_FORWARDED_FOR"),
            xfh=request.headers.get("X-Forwarded-Host"),
            xfp=request.META.get("HTTP_X_FORWARDED_PROTO"),
            fwd=request.META.get("HTTP_FORWARDED"),
        )
        return HttpResponse("ok")

    spoof: dict[str, Any] = {
        "HTTP_X_FORWARDED_FOR": "1.2.3.4",
        "HTTP_X_FORWARDED_HOST": "admin.localhost",
        "HTTP_X_FORWARDED_PROTO": "https",
        "HTTP_FORWARDED": "for=1.2.3.4",
    }
    TrustedProxyMiddleware(view)(RequestFactory().get("/", REMOTE_ADDR="203.0.113.9", **spoof))
    assert seen == {"xff": None, "xfh": None, "xfp": None, "fwd": None}
    TrustedProxyMiddleware(view)(RequestFactory().get("/", REMOTE_ADDR="10.0.0.2", **spoof))
    assert seen["xff"] == "1.2.3.4" and seen["xfh"] == "admin.localhost"


def test_middleware_sets_and_resets_request_meta(settings):
    settings.TRUSTED_PROXIES = ["127.0.0.1"]
    seen = {}

    def view(request):
        seen["meta"] = request_meta_var.get()
        return HttpResponse("ok")

    request = RequestFactory().get(
        "/", HTTP_X_FORWARDED_FOR="198.51.100.1", HTTP_USER_AGENT="Mozilla/5.0 test"
    )
    RequestContextMiddleware(view)(request)
    meta = seen["meta"]
    assert meta is not None
    assert meta.ip == "198.51.100.1"
    assert meta.user_agent == "Mozilla/5.0 test"
    assert request_meta_var.get() is None
    assert actor_var.get() is None


@pytest.mark.django_db
def test_jwt_authentication_sets_actor_with_impersonation_claims(
    staff_user, tenant_a, django_user_model
):
    admin = django_user_model.objects.create_superuser("root@example.com", "a-strong-password")
    token = AccessToken.for_user(staff_user)
    token[TENANT_CLAIM] = str(tenant_a.id)
    token[IMPERSONATOR_CLAIM] = str(admin.pk)
    token[IMPERSONATION_SESSION_CLAIM] = "0192a4f0-0000-7000-8000-000000000001"
    request = APIRequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {token}")
    # authenticate() sets request-scoped context; outside the middleware the test must reset it.
    tokens = (actor_var.set(None), tenant_id_var.set(None), user_id_var.set(None))
    try:
        TenantJWTAuthentication().authenticate(request)
        actor = actor_var.get()
    finally:
        actor_var.reset(tokens[0])
        tenant_id_var.reset(tokens[1])
        user_id_var.reset(tokens[2])
    assert actor is not None
    assert actor.user_id == staff_user.pk
    assert actor.actor_type == "STAFF"
    assert actor.impersonator_id == admin.pk
    assert str(actor.impersonation_session_id) == "0192a4f0-0000-7000-8000-000000000001"
