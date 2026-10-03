"""The Android app paying in the browser (ADR-061 item 9; owner, checkpoint review item 7): one
checkout's page only, opened by a one-minute code, never a shop session, ended by payment or
expiry."""

from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.orders.tests.helpers import make_shop, shop_client, shop_user
from apps.payments.models import CheckoutBrowserSession, PaymentIntent
from apps.payments.tests.test_online import API, checkout, intent, pay
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("daytime")]


def link(world: dict[str, Any], intent_id: str, client: Any = None) -> Any:
    return (client or world["shop_api"]).post(f"{API}/shop/payments/checkout/{intent_id}/browser/")


def code_of(url: str) -> str:
    return parse_qs(urlsplit(url).fragment)["code"][0]


def browser(host: str) -> APIClient:
    client = APIClient()
    client.defaults["HTTP_X_FORWARDED_HOST"] = host
    return client


def open_page(world: dict[str, Any], code: str, host: str = "") -> Any:
    return browser(host or f"{world['t'].slug}.localhost").post(
        f"{API}/pay/session/", {"code": code}, format="json"
    )


def page(world: dict[str, Any], token: str, host: str = "") -> Any:
    return browser(host or f"{world['t'].slug}.localhost").get(
        f"{API}/pay/checkout/", HTTP_AUTHORIZATION=f"Pay {token}"
    )


def note(world: dict[str, Any], token: str, outcome: str) -> Any:
    return browser(f"{world['t'].slug}.localhost").post(
        f"{API}/pay/checkout/outcome/",
        {"outcome": outcome},
        format="json",
        HTTP_AUTHORIZATION=f"Pay {token}",
    )


def started(world: dict[str, Any]) -> tuple[str, str]:
    body = checkout(world).json()
    made = link(world, body["id"])
    assert made.status_code == 200, made.json()
    opened = open_page(world, code_of(made.json()["url"]))
    assert opened.status_code == 200, opened.json()
    return body["id"], opened.json()["token"]


def closed(response: Any) -> bool:
    code: str = response.json()["error"]["code"] if response.status_code == 401 else ""
    return code == "PAY_PAGE_CLOSED"


@covers("shop-checkout-browser", "pay-session", "pay-checkout", "pay-checkout-outcome")
def test_the_app_pays_one_checkout_in_the_browser(world):
    body = checkout(world).json()
    made = link(world, body["id"])
    assert made.status_code == 200
    parts = urlsplit(made.json()["url"])
    assert (parts.hostname, parts.path) == ("alpha.localhost", f"/pay/{body['id']}")
    assert parts.query == ""  # the code travels in the fragment, never to a server's logs
    code = code_of(made.json()["url"])

    opened = open_page(world, code)
    assert opened.status_code == 200
    session = opened.json()
    assert session["checkout"]["id"] == body["id"] and session["checkout"]["page_open"]
    assert session["checkout"]["amount"] == "210.00"
    assert session["checkout"]["app_return_url"] == f"shopapp://shop/payments/checkout/{body['id']}"
    with tenant_context(world["t"].pk):
        row = CheckoutBrowserSession.objects.get()
        assert row.expires_at == PaymentIntent.objects.get(pk=body["id"]).expires_at
        # Only hashes are kept.
        assert code not in (row.code_hash, row.session_hash)
        assert session["token"] not in (row.code_hash, row.session_hash)
    assert closed(open_page(world, code))  # the code works once

    token = session["token"]
    assert page(world, token).json()["page_open"]
    # Never a shop session, whatever it's sent as.
    for header in (f"Pay {token}", f"Bearer {token}"):
        for path in ("/shop/home/", f"/shop/payments/checkout/{body['id']}/", "/auth/me/"):
            refused = browser("alpha.localhost").get(f"{API}{path}", HTTP_AUTHORIZATION=header)
            assert refused.status_code == 401, (header, path)

    # What the page saw is only noted; the payment comes from the gateway.
    noted = note(world, token, "success").json()
    assert (noted["status"], noted["awaiting_confirmation"]) == ("ATTEMPTED", True)
    assert intent(world, body["id"]).payment_id is None
    pay(world, body["checkout"]["order_id"])

    # Paid: the page reads it once, then its session has ended.
    final = page(world, token).json()
    assert (final["status"], final["page_open"]) == ("PAID", False)
    assert final["receipt_number"]
    assert closed(page(world, token))
    assert closed(note(world, token, "success"))
    # Back in the app, the status comes from the server.
    shown = world["shop_api"].get(f"{API}/shop/payments/checkout/{body['id']}/").json()
    assert shown["status"] == "PAID"


def test_the_code_works_for_a_minute(world):
    body = checkout(world).json()
    before = timezone.now()
    made = link(world, body["id"]).json()
    with tenant_context(world["t"].pk):
        row = CheckoutBrowserSession.objects.get()
        assert row.code_expires_at <= before + timedelta(seconds=61)
        CheckoutBrowserSession.objects.update(code_expires_at=timezone.now() - timedelta(seconds=1))
    assert closed(open_page(world, code_of(made["url"])))
    assert closed(open_page(world, "made-up"))


def test_the_page_ends_when_the_checkout_expires(world):
    intent_id, token = started(world)
    with tenant_context(world["t"].pk):
        PaymentIntent.objects.filter(pk=intent_id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
    assert closed(note(world, token, "success"))
    final = page(world, token).json()
    assert (final["status"], final["page_open"]) == ("CREATED", False)
    assert closed(page(world, token))


def test_a_closed_checkout_gets_no_page(world):
    body = checkout(world).json()
    pay(world, body["checkout"]["order_id"])
    assert closed(link(world, body["id"]))


def test_a_new_link_ends_the_earlier_page(world):
    intent_id, token = started(world)
    again = link(world, intent_id).json()
    assert closed(page(world, token))
    assert open_page(world, code_of(again["url"])).status_code == 200


def test_a_shop_that_can_no_longer_sign_in_loses_the_page(world):
    _, token = started(world)
    User.objects.filter(pk=shop_user(world["shop"]).pk).update(is_active=False)
    assert closed(page(world, token))


def test_only_the_shop_s_own_checkout_on_its_distributor_s_address(world):
    body = checkout(world).json()
    made = link(world, body["id"]).json()
    code = code_of(made["url"])
    # Another distributor's address can't open it, or use its session.
    assert closed(open_page(world, code, host="bravo.localhost"))
    assert closed(open_page(world, code, host="localhost"))
    token = open_page(world, code).json()["token"]
    assert closed(page(world, token, host="bravo.localhost"))
    # Another shop of the same distributor can't ask for this checkout's page.
    other = make_shop(world["t"], phone="9876500052")
    assert link(world, body["id"], client=shop_client(world["t"], other)).status_code == 404
    # Staff get no payment page.
    assert link(world, body["id"], client=world["staff"]).status_code == 403
