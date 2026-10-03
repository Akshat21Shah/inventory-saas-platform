"""The Android shop app's sign-in and its browser handoff for paying (ADR-061 items 4 and 9)."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts.adapters.sms import MockSmsSender
from apps.accounts.models import HandoffCode
from apps.accounts.tests.factories import make_retailer_login, make_staff_in
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db

REQUEST = "/api/v1/auth/retailer/otp/request/"
VERIFY = "/api/v1/auth/retailer/otp/verify/"
CHOOSE = "/api/v1/auth/retailer/choose-account/"
REFRESH = "/api/v1/auth/token/refresh/"
EXCHANGE = "/api/v1/auth/handoff/exchange/"
WEB_HANDOFF = "/api/v1/auth/app/web-handoff/"
PHONE = "9876543210"
GENERIC = "localhost"  # the app talks to the API on the generic address


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    MockSmsSender.outbox.clear()
    yield
    cache.clear()
    MockSmsSender.outbox.clear()


@pytest.fixture
def post(django_capture_on_commit_callbacks):
    def _post(path, data, host, client=None):
        with django_capture_on_commit_callbacks(execute=True):
            return (client or APIClient()).post(
                path, data, format="json", HTTP_X_FORWARDED_HOST=host
            )

    return _post


def _exchange(code, host):
    """As the web's handoff page does it, from that host (ADR-025's same-origin rule)."""
    return APIClient().post(
        EXCHANGE,
        {"code": code},
        format="json",
        HTTP_X_FORWARDED_HOST=host,
        HTTP_ORIGIN=f"http://{host}:3000",
        HTTP_X_REQUESTED_WITH="fetch",
    )


def _code(post):
    post(REQUEST, {"phone": PHONE}, GENERIC)
    return MockSmsSender.outbox[-1].code


def _app_client(access):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


def test_the_app_gets_its_session_at_once_with_one_distributor(tenant_a, post):
    user = make_retailer_login(tenant_a, PHONE, "Ganesh Kirana")
    done = post(VERIFY, {"phone": PHONE, "code": _code(post), "client": "app"}, GENERIC)
    assert done.status_code == 200, done.json()
    body = done.json()
    assert body["status"] == "authenticated" and "handoff" not in body
    assert AccessToken(body["access"])["tid"] == str(tenant_a.pk)
    assert RefreshToken(body["refresh"])["sub"] == str(user.pk)
    assert "rt" not in done.cookies  # the app keeps the refresh token itself

    profile = _app_client(body["access"]).get("/api/v1/auth/me/", HTTP_X_FORWARDED_HOST=GENERIC)
    assert profile.json()["retailer"]["shop_name"] == "Ganesh Kirana"

    renewed = post(REFRESH, {"refresh": body["refresh"]}, GENERIC).json()
    assert renewed["access"] and renewed["refresh"] != body["refresh"]
    reused = post(REFRESH, {"refresh": body["refresh"]}, GENERIC)
    assert reused.status_code == 401  # rotated: the old one is spent


def test_the_web_still_gets_a_handoff_on_the_generic_address(tenant_a, post):
    make_retailer_login(tenant_a, PHONE)
    body = post(VERIFY, {"phone": PHONE, "code": _code(post)}, GENERIC).json()
    assert body["status"] == "handoff" and "access" not in body and "refresh" not in body


def test_the_app_chooses_among_several_distributors(tenant_a, tenant_b, post):
    make_retailer_login(tenant_a, PHONE, "Ganesh (A)")
    user_b = make_retailer_login(tenant_b, PHONE, "Ganesh (B)")
    body = post(VERIFY, {"phone": PHONE, "code": _code(post), "client": "app"}, GENERIC).json()
    assert body["status"] == "choose_account" and "access" not in body
    assert sorted((a["tenant_slug"], a["shop_name"]) for a in body["accounts"]) == [
        ("alpha", "Ganesh (A)"),
        ("bravo", "Ganesh (B)"),
    ]
    chosen = post(
        CHOOSE,
        {"choice_token": body["choice_token"], "choice_id": str(user_b.pk), "client": "app"},
        GENERIC,
    )
    session = chosen.json()
    assert session["status"] == "authenticated" and "rt" not in chosen.cookies
    assert AccessToken(session["access"])["tid"] == str(tenant_b.pk)
    assert RefreshToken(session["refresh"])["sub"] == str(user_b.pk)


def _app_session(tenant, post):
    make_retailer_login(tenant, PHONE)
    body = post(VERIFY, {"phone": PHONE, "code": _code(post), "client": "app"}, GENERIC).json()
    return _app_client(body["access"])


def _handoff(url):
    parts = urlsplit(url)
    fragment = parse_qs(parts.fragment)
    return parts, fragment["code"][0], fragment["next"][0]


@covers("auth-app-web-handoff")
def test_the_app_opens_a_shop_page_signed_in_once(tenant_a, tenant_b, post):
    client = _app_session(tenant_a, post)
    made = post(WEB_HANDOFF, {"next": "/shop/payments/checkout/abc"}, GENERIC, client=client)
    assert made.status_code == 200, made.json()
    parts, code, next_path = _handoff(made.json()["url"])
    assert parts.hostname == "alpha.localhost" and parts.path == "/auth/handoff"
    assert parts.query == ""  # the code travels in the fragment, never to a server's logs
    assert next_path == "/shop/payments/checkout/abc"

    # Another distributor's address can't use it.
    assert _exchange(code, "bravo.localhost").json()["error"]["code"] == ("TOKEN_INVALID")
    made = post(WEB_HANDOFF, {"next": "/shop/payments"}, GENERIC, client=client)
    _, code, _ = _handoff(made.json()["url"])
    signed_in = _exchange(code, "alpha.localhost")
    assert signed_in.json()["status"] == "authenticated"
    # The browser session ends on its own within the hour, even after a refresh.
    end = timezone.now() + timedelta(hours=1, seconds=5)
    refresh = RefreshToken(signed_in.cookies["rt"].value)
    assert refresh["exp"] <= end.timestamp()
    renewed = post(REFRESH, {"refresh": signed_in.cookies["rt"].value}, "alpha.localhost").json()
    assert RefreshToken(renewed["refresh"])["exp"] <= end.timestamp()
    # Single use.
    assert _exchange(code, "alpha.localhost").json()["error"]["code"] == ("TOKEN_INVALID")


def test_a_web_handoff_expires_within_a_minute(tenant_a, post):
    client = _app_session(tenant_a, post)
    before = timezone.now()
    made = post(WEB_HANDOFF, {"next": "/shop/payments"}, GENERIC, client=client)
    _, code, _ = _handoff(made.json()["url"])
    handoff = HandoffCode.objects.get()
    assert handoff.expires_at <= before + timedelta(seconds=61)
    HandoffCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert _exchange(code, "alpha.localhost").json()["error"]["code"] == ("TOKEN_INVALID")


@pytest.mark.parametrize(
    "next_path",
    ["/manage", "//evil.example/shop", "https://evil.example/shop", "/shop/../manage", "/shopx"],
)
def test_a_web_handoff_opens_only_shop_pages(tenant_a, post, next_path):
    client = _app_session(tenant_a, post)
    refused = post(WEB_HANDOFF, {"next": next_path}, GENERIC, client=client)
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "VALIDATION_ERROR"


def test_staff_get_no_web_handoff(tenant_a, api_client_for, post):
    staff = make_staff_in(tenant_a, "OWNER")
    refused = post(
        WEB_HANDOFF, {"next": "/shop"}, "alpha.localhost", client=api_client_for(staff, tenant_a)
    )
    assert refused.status_code == 403
