"""Languages (ADR-060): the manifest is the only list; which languages a person may choose (the
platform's enabled list, every language for super admins and test distributors); the language
a person sees; a shop that hasn't chosen follows its distributor's default; sign-in pages; the
request's language from Accept-Language."""

import json
from pathlib import Path
from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in, make_super_admin
from apps.accounts.tokens import issue_tokens
from apps.orders.tests.helpers import client_for, make_shop, settings, shop_client
from apps.platform.services import set_platform_settings
from apps.retailers.models import Retailer
from common import languages
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"


@pytest.fixture(autouse=True)
def _fresh_settings():
    cache.clear()
    yield
    cache.clear()


def platform(**values: str) -> None:
    set_platform_settings(values, user=None)
    cache.clear()


def codes(body: dict[str, Any]) -> list[str]:
    return [row["code"] for row in body["languages"]]


def test_the_manifest_is_the_only_list_and_the_web_has_the_same():
    assert languages.codes() == ("en", "hi", "mr")
    hindi = languages.get("hi")
    assert hindi is not None and hindi.native == "हिन्दी"
    assert languages.by_any_name()["marathi"] == "mr"
    assert languages.by_any_name()["मराठी"] == "mr"
    web = Path(__file__).resolve().parents[3] / "web" / "lib" / "i18n" / "languages.json"
    ours = Path(languages.MANIFEST)
    assert json.loads(web.read_text()) == json.loads(ours.read_text())


def test_only_enabled_languages_except_for_super_admins_and_test_distributors(tenant_a):
    assert languages.enabled() == ("en",)  # Hindi and Marathi wait for their review
    assert languages.available(tenant_slug=tenant_a.slug) == ("en",)
    assert languages.available(platform_user=True) == ("en", "hi", "mr")
    platform(**{"platform.language_test_tenants": tenant_a.slug})
    assert languages.available(tenant_slug=tenant_a.slug) == ("en", "hi", "mr")
    assert languages.available(tenant_slug="someone-else") == ("en",)
    platform(**{"platform.languages_enabled": "en,mr,xx"})  # unknown codes are ignored
    assert languages.enabled() == ("en", "mr")


def test_me_says_which_language_a_person_sees_and_may_choose(tenant_a):
    owner = client_for(tenant_a, make_staff_in(tenant_a, "OWNER"))
    me = owner.get(f"{API}/auth/me/").json()
    assert (me["language"], codes(me)) == ("en", ["en"])
    refused = owner.patch(f"{API}/auth/me/", {"preferred_language": "hi"}, format="json")
    assert refused.status_code == 400
    assert "preferred_language" in refused.json()["error"]["details"]["fields"]

    platform(**{"platform.language_test_tenants": tenant_a.slug})
    saved = owner.patch(f"{API}/auth/me/", {"preferred_language": "mr"}, format="json")
    assert saved.status_code == 200
    assert (saved.json()["language"], codes(saved.json())) == ("mr", ["en", "hi", "mr"])

    platform(**{"platform.language_test_tenants": ""})  # no longer testing: English again
    me = owner.get(f"{API}/auth/me/").json()
    assert (me["preferred_language"], me["language"]) == ("mr", "en")


def test_super_admins_may_use_every_language(db):
    admin = APIClient()
    admin.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(make_super_admin(), None).access}")
    admin.defaults["HTTP_X_FORWARDED_HOST"] = "admin.localhost"
    saved = admin.patch(f"{API}/auth/me/", {"preferred_language": "hi"}, format="json")
    assert saved.status_code == 200
    assert (saved.json()["language"], codes(saved.json())) == ("hi", ["en", "hi", "mr"])


def test_a_shop_follows_its_distributors_default_unless_it_chooses(tenant_a):
    platform(**{"platform.language_test_tenants": tenant_a.slug})
    shop = make_shop(tenant_a, "9876500181")
    assert shop.preferred_language == ""  # follows the default
    settings(tenant_a, retailers__default_language="mr")
    with tenant_context(tenant_a.pk):
        assert languages.shop_language(Retailer.objects.get(pk=shop.pk)) == "mr"
    client = shop_client(tenant_a, shop)
    assert client.get(f"{API}/auth/me/").json()["language"] == "mr"
    chosen = client.patch(f"{API}/auth/me/", {"preferred_language": "hi"}, format="json")
    assert chosen.json()["language"] == "hi"
    with tenant_context(tenant_a.pk):  # the shop's messages and documents follow it
        assert Retailer.objects.get(pk=shop.pk).preferred_language == "hi"


def test_a_language_the_distributor_may_not_use_falls_back_to_english(tenant_a):
    settings(tenant_a, retailers__default_language="hi")
    shop = make_shop(tenant_a, "9876500182")
    with tenant_context(tenant_a.pk):
        assert languages.shop_language(Retailer.objects.get(pk=shop.pk)) == "en"


@covers("public-tenant-branding")
def test_sign_in_pages_get_the_languages_and_the_default(tenant_a):
    client = APIClient()
    body = client.get(f"{API}/public/tenants/{tenant_a.slug}/branding/").json()
    assert (codes(body), body["default_language"]) == (["en"], "en")
    platform(**{"platform.language_test_tenants": tenant_a.slug})
    settings(tenant_a, retailers__default_language="mr")
    body = client.get(f"{API}/public/tenants/{tenant_a.slug}/branding/").json()
    assert (codes(body), body["default_language"]) == (["en", "hi", "mr"], "mr")
    assert body["languages"][1] == {"code": "hi", "name": "Hindi", "native": "हिन्दी"}


@covers("public-languages")
def test_the_super_admins_sign_in_page_lists_every_language(db):
    platform(**{"platform.languages_enabled": "en,hi"})
    rows = APIClient().get(f"{API}/public/languages/").json()
    assert [(r["code"], r["enabled"]) for r in rows] == [("en", True), ("hi", True), ("mr", False)]


def test_the_request_speaks_the_language_the_web_asks_for(tenant_a):
    owner = client_for(tenant_a, make_staff_in(tenant_a, "OWNER"))
    # Django's own messages come translated where Django has them (Hindi does).
    english = owner.post(f"{API}/retailers/", {}, format="json", HTTP_ACCEPT_LANGUAGE="en")
    hindi = owner.post(f"{API}/retailers/", {}, format="json", HTTP_ACCEPT_LANGUAGE="hi")
    assert english.status_code == hindi.status_code == 400
    assert english.json() != hindi.json() or english.headers.get("Content-Language") == "en"
    assert hindi.headers.get("Content-Language") == "hi"
