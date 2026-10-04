"""The Android app's settings and required updates (ADR-061 item 6); the shop's distributor
contact for the app's Privacy and data page (item 18)."""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_retailer_login, make_staff_in
from apps.platform import services
from apps.platform.app_client import parse_version
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db

CONFIG = "/api/v1/app/config/"
SHOP_HOME = "/api/v1/shop/home/"


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


def _settings(**values):
    services.set_platform_settings({f"platform.{k}": v for k, v in values.items()}, user=None)
    cache.clear()


@covers("app-config")
def test_the_app_reads_its_settings_without_signing_in():
    assert APIClient().get(CONFIG).json() == {
        "min_version": "0.0.0",
        "latest_version": "",
        "privacy_policy_url": "",
    }
    _settings(
        app_min_version="1.2.0",
        app_latest_version="1.3.0",
        privacy_policy_url="https://example.com/privacy",
    )
    assert APIClient().get(CONFIG).json() == {
        "min_version": "1.2.0",
        "latest_version": "1.3.0",
        "privacy_policy_url": "https://example.com/privacy",
    }


@pytest.mark.parametrize(
    ("version", "refused"),
    [("1.1.9", True), ("0.9.0", True), ("not-a-version", True), ("1.2.0", False), ("2.0.0", False)],
)
def test_too_old_apps_are_asked_to_update(tenant_a, api_client_for, version, refused):
    _settings(app_min_version="1.2.0")
    client = api_client_for(make_retailer_login(tenant_a, "9876543210"), tenant_a)
    response = client.get(SHOP_HOME, HTTP_X_APP_VERSION=version)
    if refused:
        assert response.status_code == 426
        assert response.json()["error"]["code"] == "APP_UPDATE_REQUIRED"
        assert response.json()["error"]["details"] == {"min_version": "1.2.0"}
    else:
        assert response.status_code == 200
    # The settings always answer: an old app must learn what to do.
    assert APIClient().get(CONFIG, HTTP_X_APP_VERSION=version).status_code == 200


def test_the_web_and_new_apps_are_never_refused(tenant_a, api_client_for):
    _settings(app_min_version="9.9.9")
    client = api_client_for(make_retailer_login(tenant_a, "9876543210"), tenant_a)
    assert client.get(SHOP_HOME).status_code == 200  # no version header: the web


def test_the_update_message_is_in_the_apps_language(tenant_a, api_client_for):
    _settings(app_min_version="1.2.0")
    client = api_client_for(make_retailer_login(tenant_a, "9876543210"), tenant_a)
    response = client.get(SHOP_HOME, HTTP_X_APP_VERSION="1.0.0", HTTP_ACCEPT_LANGUAGE="hi")
    assert response.json()["error"]["message"] == (
        "ऐप का यह संस्करण बहुत पुराना है। आगे बढ़ने के लिए इसे अपडेट करें।"
    )


def test_versions_must_be_three_numbers():
    assert parse_version("1.10.3") == (1, 10, 3)
    assert parse_version(" 2.0.0 ") == (2, 0, 0)
    assert (
        parse_version("1.2") is None and parse_version("") is None and parse_version(None) is None
    )
    with pytest.raises(services.SettingsInvalid):
        _settings(app_min_version="1.2")


@covers("shop-distributor")
def test_a_shop_sees_its_own_distributors_contact(tenant_a, tenant_b, api_client_for):
    shop_a = api_client_for(make_retailer_login(tenant_a, "9876543210"), tenant_a)
    shop_b = api_client_for(make_retailer_login(tenant_b, "9876543210"), tenant_b)
    contact_a = shop_a.get("/api/v1/shop/distributor/").json()
    contact_b = shop_b.get("/api/v1/shop/distributor/").json()
    assert contact_a == {"name": tenant_a.name, "phone": tenant_a.phone, "email": tenant_a.email}
    assert contact_b == {"name": tenant_b.name, "phone": tenant_b.phone, "email": tenant_b.email}
    staff = api_client_for(make_staff_in(tenant_a, "OWNER"), tenant_a)
    assert staff.get("/api/v1/shop/distributor/").status_code == 403
