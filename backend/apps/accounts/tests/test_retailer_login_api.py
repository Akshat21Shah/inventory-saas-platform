"""Retailer sign-in with mobile number + one-time code (spec 5.2, ADR-015, ADR-020)."""

import secrets
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.db import connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.adapters.sms import MockSmsSender
from apps.accounts.models import OTPRequest, User
from apps.accounts.tests.factories import make_retailer_login
from apps.platform.models import Tenant
from apps.platform.tests.factories import TenantFactory
from apps.retailers.models import Retailer
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db

REQUEST = "/api/v1/auth/retailer/otp/request/"
VERIFY = "/api/v1/auth/retailer/otp/verify/"
CHOOSE = "/api/v1/auth/retailer/choose-account/"
PHONE = "9876543210"
E164 = "+919876543210"


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    MockSmsSender.outbox.clear()
    yield
    cache.clear()
    MockSmsSender.outbox.clear()


@pytest.fixture
def post(django_capture_on_commit_callbacks):
    def _post(path, data, host, ip="198.51.100.20", client=None):
        with django_capture_on_commit_callbacks(execute=True):
            return (client or APIClient()).post(
                path, data, format="json", HTTP_X_FORWARDED_HOST=host, HTTP_X_FORWARDED_FOR=ip
            )

    return _post


def _last_code():
    assert MockSmsSender.outbox, "no SMS was sent"
    return MockSmsSender.outbox[-1].code


# --- Subdomain sign-in --------------------------------------------------------------------------


@covers("auth-retailer-otp-request", "auth-retailer-otp-verify")
def test_retailer_signs_in_on_their_distributors_subdomain(tenant_a, post):
    user = make_retailer_login(tenant_a, PHONE, "Ganesh Kirana")
    sent = post(REQUEST, {"phone": "+91 98765-43210"}, "alpha.localhost")
    assert sent.status_code == 202
    assert sent.json() == {"expires_in": 300, "resend_after": 30}
    assert MockSmsSender.outbox[-1].phone == E164
    assert MockSmsSender.outbox[-1].sender_name == tenant_a.name

    done = post(VERIFY, {"phone": PHONE, "code": _last_code()}, "alpha.localhost")
    assert done.status_code == 200, done.json()
    body = done.json()
    assert body["status"] == "authenticated"
    assert body["user_type"] == "RETAILER"
    claims = AccessToken(body["access"])
    assert (claims["sub"], claims["tid"], claims["utype"]) == (
        str(user.pk),
        str(tenant_a.pk),
        "RETAILER",
    )
    assert "rt" in done.cookies

    me = APIClient()
    me.credentials(HTTP_AUTHORIZATION=f"Bearer {body['access']}")
    profile = me.get("/api/v1/auth/me/", HTTP_X_FORWARDED_HOST="alpha.localhost").json()
    assert profile["retailer"]["shop_name"] == "Ganesh Kirana"
    assert profile["permissions"] == []
    assert profile["role"] is None


def test_request_looks_identical_for_unknown_numbers_and_sends_nothing(tenant_a, post):
    make_retailer_login(tenant_a, PHONE)
    known = post(REQUEST, {"phone": PHONE}, "alpha.localhost")
    unknown = post(REQUEST, {"phone": "9123456780"}, "alpha.localhost")
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert [m.phone for m in MockSmsSender.outbox] == [E164]
    assert OTPRequest.objects.filter(phone="+919123456780").exists()  # recorded all the same
    wrong = post(VERIFY, {"phone": "9123456780", "code": "000000"}, "alpha.localhost")
    assert wrong.json()["error"]["code"] == "OTP_INVALID"


def test_number_of_another_distributor_gets_no_code_on_this_subdomain(tenant_a, tenant_b, post):
    """Isolation: a retailer of A cannot sign in on B's subdomain, and B learns nothing."""
    make_retailer_login(tenant_a, PHONE)
    on_b = post(REQUEST, {"phone": PHONE}, "bravo.localhost")
    assert on_b.status_code == 202
    assert MockSmsSender.outbox == []
    post(REQUEST, {"phone": PHONE}, "alpha.localhost")
    code_for_a = _last_code()
    cross = post(VERIFY, {"phone": PHONE, "code": code_for_a}, "bravo.localhost")
    assert cross.json()["error"]["code"] == "OTP_INVALID"


def test_same_number_under_two_distributors_are_separate_accounts(tenant_a, tenant_b, post):
    user_a = make_retailer_login(tenant_a, PHONE, "Shop at A")
    user_b = make_retailer_login(tenant_b, PHONE, "Shop at B")
    assert user_a.pk != user_b.pk
    post(REQUEST, {"phone": PHONE}, "bravo.localhost")
    body = post(VERIFY, {"phone": PHONE, "code": _last_code()}, "bravo.localhost").json()
    assert AccessToken(body["access"])["sub"] == str(user_b.pk)


def test_code_is_single_use_and_expires(tenant_a, post):
    make_retailer_login(tenant_a, PHONE)
    post(REQUEST, {"phone": PHONE}, "alpha.localhost")
    code = _last_code()
    assert post(VERIFY, {"phone": PHONE, "code": code}, "alpha.localhost").status_code == 200
    assert (
        post(VERIFY, {"phone": PHONE, "code": code}, "alpha.localhost").json()["error"]["code"]
        == "OTP_INVALID"
    )

    post(REQUEST, {"phone": PHONE}, "alpha.localhost")
    OTPRequest.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert (
        post(VERIFY, {"phone": PHONE, "code": _last_code()}, "alpha.localhost").json()["error"][
            "code"
        ]
        == "OTP_INVALID"
    )


def test_five_wrong_codes_burn_the_code(tenant_a, post):
    make_retailer_login(tenant_a, PHONE)
    post(REQUEST, {"phone": PHONE}, "alpha.localhost")
    code = _last_code()
    wrong = "111111" if code != "111111" else "222222"
    for _ in range(5):
        assert post(VERIFY, {"phone": PHONE, "code": wrong}, "alpha.localhost").status_code == 400
    assert (
        post(VERIFY, {"phone": PHONE, "code": code}, "alpha.localhost").json()["error"]["code"]
        == "OTP_INVALID"
    )


def test_invalid_phone_is_a_field_error(tenant_a, post):
    response = post(REQUEST, {"phone": "12345"}, "alpha.localhost")
    assert response.status_code == 400
    assert "phone" in response.json()["error"]["details"]["fields"]


def test_otp_rate_limits_per_phone_and_generous_per_ip(tenant_a, post):
    make_retailer_login(tenant_a, PHONE)
    for _ in range(3):
        assert post(REQUEST, {"phone": PHONE}, "alpha.localhost").status_code == 202
    limited = post(REQUEST, {"phone": PHONE}, "alpha.localhost")
    assert limited.status_code == 429 and int(limited["Retry-After"]) > 0
    # Many shops behind one carrier IP: 100 requests per hour from one IP are fine.
    for i in range(96):
        assert (
            post(REQUEST, {"phone": f"9{i:09d}"}, "alpha.localhost", ip="203.0.113.9").status_code
            == 202
        )


def test_inactive_retailer_gets_no_code_and_loses_access(tenant_a, post):
    user = make_retailer_login(tenant_a, PHONE)
    post(REQUEST, {"phone": PHONE}, "alpha.localhost")
    access = post(VERIFY, {"phone": PHONE, "code": _last_code()}, "alpha.localhost").json()[
        "access"
    ]
    Retailer.objects.unscoped().update(is_active=False)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert (
        client.get("/api/v1/auth/me/", HTTP_X_FORWARDED_HOST="alpha.localhost").status_code == 401
    )
    MockSmsSender.outbox.clear()
    post(REQUEST, {"phone": PHONE}, "alpha.localhost")
    assert MockSmsSender.outbox == []
    assert user.is_active  # the login itself is untouched; the retailer is inactive


def test_retailer_token_is_refused_on_another_subdomain(tenant_a, post):
    make_retailer_login(tenant_a, PHONE)
    post(REQUEST, {"phone": PHONE}, "alpha.localhost")
    access = post(VERIFY, {"phone": PHONE, "code": _last_code()}, "alpha.localhost").json()[
        "access"
    ]
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert (
        client.get("/api/v1/auth/me/", HTTP_X_FORWARDED_HOST="bravo.localhost").status_code == 401
    )


def test_admin_host_does_not_serve_retailer_sign_in(tenant_a, post):
    make_retailer_login(tenant_a, PHONE)
    assert (
        post(REQUEST, {"phone": PHONE}, "admin.localhost").json()["error"]["code"] == "OTP_INVALID"
    )


# --- Generic domain: distributor chooser (ADR-015) ----------------------------------------------


def _exchange(code, host):
    return APIClient().post(
        "/api/v1/auth/handoff/exchange/",
        {"code": code},
        format="json",
        HTTP_X_FORWARDED_HOST=host,
        HTTP_ORIGIN=f"http://{host}:3000",
        HTTP_X_REQUESTED_WITH="fetch",
    )


def test_generic_domain_single_account_hands_off_to_its_subdomain(tenant_a, post):
    user = make_retailer_login(tenant_a, PHONE)
    post(REQUEST, {"phone": PHONE}, "localhost")
    body = post(VERIFY, {"phone": PHONE, "code": _last_code()}, "localhost").json()
    assert body["status"] == "handoff"
    assert body["handoff"]["tenant_slug"] == tenant_a.slug
    done = _exchange(body["handoff"]["code"], "alpha.localhost").json()
    assert done["status"] == "authenticated" and done["user_type"] == "RETAILER"
    assert AccessToken(done["access"])["sub"] == str(user.pk)


@covers("auth-retailer-choose-account")
def test_generic_domain_lists_only_the_phones_active_accounts(tenant_a, tenant_b, post):
    make_retailer_login(tenant_a, PHONE, "Ganesh Kirana (A)")
    user_b = make_retailer_login(tenant_b, PHONE, "Ganesh Kirana (B)")
    suspended = TenantFactory.create(name="Zeta Traders", status=Tenant.Status.SUSPENDED)
    make_retailer_login(suspended, PHONE, "Hidden")
    make_retailer_login(TenantFactory.create(name="Other"), "9123456780", "Someone else")

    post(REQUEST, {"phone": PHONE}, "localhost")
    body = post(VERIFY, {"phone": PHONE, "code": _last_code()}, "localhost").json()
    assert body["status"] == "choose_account"
    assert "access" not in body
    assert sorted(a["shop_name"] for a in body["accounts"]) == [
        "Ganesh Kirana (A)",
        "Ganesh Kirana (B)",
    ]

    stranger = User.objects.get(phone="+919123456780")
    refused = post(
        CHOOSE, {"choice_token": body["choice_token"], "choice_id": str(stranger.pk)}, "localhost"
    )
    assert refused.json()["error"]["code"] == "TOKEN_INVALID"

    post(REQUEST, {"phone": PHONE}, "localhost")
    body = post(VERIFY, {"phone": PHONE, "code": _last_code()}, "localhost").json()
    chosen = post(
        CHOOSE, {"choice_token": body["choice_token"], "choice_id": str(user_b.pk)}, "localhost"
    ).json()
    assert chosen["status"] == "handoff" and chosen["handoff"]["tenant_slug"] == tenant_b.slug
    again = post(
        CHOOSE, {"choice_token": body["choice_token"], "choice_id": str(user_b.pk)}, "localhost"
    )
    assert again.json()["error"]["code"] == "TOKEN_INVALID"
    assert (
        _exchange(chosen["handoff"]["code"], "alpha.localhost").json()["error"]["code"]
        == "TOKEN_INVALID"
    )


def test_retailer_is_not_subject_to_the_staff_2fa_policy(tenant_a, post):
    from apps.accounts.tests.factories import make_staff_in
    from apps.platform import services as platform_services
    from common.tenancy import tenant_context

    owner = make_staff_in(tenant_a, "OWNER")
    with tenant_context(tenant_a.id):
        platform_services.set_tenant_settings({"security.require_staff_2fa": True}, user=owner)
    cache.clear()
    make_retailer_login(tenant_a, PHONE)
    post(REQUEST, {"phone": PHONE}, "alpha.localhost")
    assert (
        post(VERIFY, {"phone": PHONE, "code": _last_code()}, "alpha.localhost").json()["status"]
        == "authenticated"
    )


def test_otp_requests_are_protected_by_rls(tenant_a, tenant_b, post):
    make_retailer_login(tenant_a, PHONE)
    post(REQUEST, {"phone": PHONE}, "alpha.localhost")
    post(REQUEST, {"phone": "9000000001"}, "localhost")
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE app_user")
        cursor.execute("SELECT set_config('app.current_tenant', %s, true)", [str(tenant_b.pk)])
        cursor.execute("SELECT phone FROM accounts_otprequest")
        assert [r[0] for r in cursor.fetchall()] == ["+919000000001"]  # only the tenant-less row
        cursor.execute("RESET ROLE")


def test_dev_fixed_code_only_with_mock_allowance(settings, tenant_a, post, monkeypatch):
    from django.core.exceptions import ImproperlyConfigured

    from apps.accounts import retailer_login
    from apps.accounts.adapters.sms import get_sms_sender

    settings.OTP_FIXED_CODE = "123456"
    make_retailer_login(tenant_a, PHONE)
    post(REQUEST, {"phone": PHONE}, "alpha.localhost")
    assert _last_code() == "123456"

    settings.ALLOW_MOCK_INTEGRATIONS = False
    monkeypatch.setattr(secrets, "randbelow", lambda _: 42)
    assert retailer_login._new_code() == "000042"  # the fixed code is ignored
    with pytest.raises(ImproperlyConfigured):
        get_sms_sender()  # and the mock sender is refused


def test_deploy_check_refuses_mock_sms_and_fixed_code(settings):
    from apps.accounts.checks import mock_integrations_check

    settings.ALLOW_MOCK_INTEGRATIONS = True
    settings.OTP_FIXED_CODE = None
    assert mock_integrations_check(None) == []
    settings.ALLOW_MOCK_INTEGRATIONS = False
    settings.OTP_FIXED_CODE = "123456"
    assert {e.id for e in mock_integrations_check(None)} == {"accounts.E001", "accounts.E002"}


@pytest.mark.parametrize("status", [Tenant.Status.SUSPENDED, Tenant.Status.ONBOARDING])
def test_unavailable_distributor_gives_the_neutral_answer_on_its_subdomain(tenant_a, post, status):
    make_retailer_login(tenant_a, PHONE)
    Tenant.objects.filter(pk=tenant_a.pk).update(status=status)
    for path, body in ((REQUEST, {"phone": PHONE}), (VERIFY, {"phone": PHONE, "code": "123456"})):
        response = post(path, body, "alpha.localhost")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "TENANT_UNAVAILABLE"
    assert MockSmsSender.outbox == []


def test_generic_domain_tells_the_verified_owner_their_distributor_is_unavailable(tenant_a, post):
    make_retailer_login(tenant_a, PHONE)
    Tenant.objects.filter(pk=tenant_a.pk).update(status=Tenant.Status.SUSPENDED)
    post(REQUEST, {"phone": PHONE}, "localhost")
    response = post(VERIFY, {"phone": PHONE, "code": _last_code()}, "localhost")
    assert response.json()["error"]["code"] == "TENANT_UNAVAILABLE"
    wrong = post(VERIFY, {"phone": "9123456780", "code": "000000"}, "localhost")
    assert wrong.json()["error"]["code"] == "OTP_INVALID"  # unknown numbers learn nothing


def test_shop_on_hold_signs_in_by_default_but_is_told_when_refused(tenant_a, post):
    """ADR-036: ``retailers.blocked_can_sign_in`` (default on)."""
    from apps.platform.models import TenantSetting
    from apps.retailers.models import Retailer

    make_retailer_login(tenant_a, PHONE)
    with tenant_context(tenant_a.pk):
        Retailer.objects.update(status="BLOCKED", blocked_reason="Overdue")
    host = "alpha.localhost"
    post(REQUEST, {"phone": PHONE}, host)
    signed_in = post(VERIFY, {"phone": PHONE, "code": _last_code()}, host)
    assert signed_in.json()["status"] == "authenticated"

    with tenant_context(tenant_a.pk):
        TenantSetting.objects.create(key="retailers.blocked_can_sign_in", value=False)
    cache.clear()
    post(REQUEST, {"phone": PHONE}, host)
    refused = post(VERIFY, {"phone": PHONE, "code": _last_code()}, host)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "RETAILER_ON_HOLD"
