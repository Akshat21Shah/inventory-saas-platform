"""The Android shop app's sign-in (ADR-061 item 4). Paying in the browser (item 9):
apps/payments/tests/test_browser_pay.py."""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts.adapters.sms import MockSmsSender
from apps.accounts.tests.factories import make_retailer_login

pytestmark = pytest.mark.django_db

REQUEST = "/api/v1/auth/retailer/otp/request/"
VERIFY = "/api/v1/auth/retailer/otp/verify/"
CHOOSE = "/api/v1/auth/retailer/choose-account/"
REFRESH = "/api/v1/auth/token/refresh/"
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
