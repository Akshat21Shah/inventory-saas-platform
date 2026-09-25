"""Django admin: super admins only, admin host only, password + TOTP, read-only (PLAN 1.13)."""

import pyotp
import pytest
from django.contrib import admin
from django.core.cache import cache
from django.test import Client

from apps.accounts.tests.factories import enable_totp, make_staff_in, make_super_admin
from common.admin_site import ReadOnlyPlatformAdmin

pytestmark = pytest.mark.django_db
PASSWORD = "a-strong-password"


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


def _login(client, email, otp):
    return client.post(
        "/django-admin/login/?next=/django-admin/",
        {"username": email, "password": PASSWORD, "otp": otp},
    )


@pytest.fixture
def root():
    user = make_super_admin("root@platform.example.com")
    return user, enable_totp(user)


def test_super_admin_signs_in_with_password_and_code_on_the_admin_host(root, tenant_a):
    user, secret = root
    client = Client(HTTP_HOST="admin.localhost")
    assert client.get("/django-admin/").status_code == 302  # to the login page
    response = _login(client, user.email, pyotp.TOTP(secret).now())
    assert response.status_code == 302, response.content[:500]
    assert client.get("/django-admin/").status_code == 200
    page = client.get("/django-admin/platform/tenant/")
    assert page.status_code == 200
    assert tenant_a.name.encode() in page.content


def test_password_alone_is_not_enough(root):
    user, _ = root
    client = Client(HTTP_HOST="admin.localhost")
    response = _login(client, user.email, "000000")
    assert response.status_code == 200  # the form again, with an error
    assert client.get("/django-admin/").status_code == 302


def test_not_on_other_hosts(root):
    user, secret = root
    client = Client(HTTP_HOST="alpha.localhost")
    assert _login(client, user.email, pyotp.TOTP(secret).now()).status_code == 200
    assert client.get("/django-admin/").status_code == 302


def test_staff_cannot_use_the_admin(tenant_a):
    staff = make_staff_in(tenant_a, "OWNER", email="owner@example.com")
    secret = enable_totp(staff)
    client = Client(HTTP_HOST="admin.localhost")
    assert _login(client, staff.email, pyotp.TOTP(secret).now()).status_code == 200
    assert client.get("/django-admin/").status_code == 302


def test_admin_sign_in_counts_towards_lockout(root):
    user, _ = root
    client = Client(HTTP_HOST="admin.localhost")
    client.post("/django-admin/login/", {"username": user.email, "password": "wrong", "otp": "1"})
    user.refresh_from_db()
    assert user.failed_login_count == 1


def test_everything_is_read_only(root, tenant_a):
    user, secret = root
    client = Client(HTTP_HOST="admin.localhost")
    _login(client, user.email, pyotp.TOTP(secret).now())
    assert client.get("/django-admin/platform/tenant/add/").status_code == 403
    assert (
        client.post(
            f"/django-admin/platform/tenant/{tenant_a.pk}/change/", {"name": "x"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/django-admin/platform/tenant/{tenant_a.pk}/delete/", {"post": "yes"}
        ).status_code
        == 403
    )
    assert all(isinstance(a, ReadOnlyPlatformAdmin) for a in admin.site._registry.values())


def test_secrets_are_never_shown(root):
    user, secret = root
    client = Client(HTTP_HOST="admin.localhost")
    _login(client, user.email, pyotp.TOTP(secret).now())
    page = client.get(f"/django-admin/accounts/user/{user.pk}/change/")
    assert page.status_code == 200
    assert secret.encode() not in page.content
    assert user.password.encode() not in page.content
