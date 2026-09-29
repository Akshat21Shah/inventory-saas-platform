"""Payment gateway settings and adapters (ADR-049 items 7, 9 and 11): only with the module on; keys
encrypted, masked and checked in the background; test keys only unless live payments are allowed
here; per tenant, owner only. The mock gateway's signed webhooks, and the Razorpay adapter through
its SDK (the SDK's network calls faked; the signature check real). Staff can't record an online
payment by hand."""

import hashlib
import hmac
import json
from datetime import date
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import connection

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.orders.tests.helpers import client_for, make_shop
from apps.payments.gateway import get_gateway
from apps.payments.gateway.base import GatewayError, GatewayKeys, SignatureInvalid
from apps.payments.gateway.mock import MockGateway
from apps.payments.gateway.razorpay import RazorpayGateway
from apps.platform import selectors
from apps.platform.models import FeatureFlag, TenantFeature
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"
URL = f"{API}/settings/payment-gateway/"
MOCK_KEYS = {
    "provider": "MOCK",
    "mode": "TEST",
    "key_id": "mock_key_123",
    "key_secret": "secret-4567",
    "webhook_secret": "hook-8901",
}
KEYS = GatewayKeys("MOCK", "TEST", "mock_key_123", "secret-4567", "hook-8901")


def payments_on(tenant: Any) -> None:
    with tenant_context(tenant.pk):
        TenantFeature.objects.update_or_create(
            flag=FeatureFlag.objects.get(code="payments"), defaults={"enabled": True}
        )
    selectors.invalidate_tenant_features(tenant.pk)


@pytest.fixture
def world(tenant_a, tenant_b, django_capture_on_commit_callbacks):
    owner = make_staff_in(tenant_a, "OWNER")
    return {
        "t": tenant_a,
        "tb": tenant_b,
        "owner": client_for(tenant_a, owner),
        "manager": client_for(tenant_a, make_staff_in(tenant_a, "MANAGER")),
        "other": client_for(tenant_b, make_staff_in(tenant_b, "OWNER")),
        "run": lambda: django_capture_on_commit_callbacks(execute=True),
    }


@covers("payment-gateway", "payment-gateway-verify")
def test_gateway_settings_need_the_module(world):
    for call in (
        world["owner"].get(URL),
        world["owner"].put(URL, MOCK_KEYS, format="json"),
        world["owner"].post(f"{URL}verify/"),
    ):
        assert (call.status_code, call.json()["error"]["code"]) == (403, "MODULE_NOT_ENABLED")


def test_the_owner_saves_and_checks_the_keys(world):
    payments_on(world["t"])
    empty = world["owner"].get(URL).json()
    assert (empty["status"], empty["providers"]) == ("UNVERIFIED", ["RAZORPAY", "MOCK"])
    assert empty["webhook_url"].endswith(
        f"/api/v1/webhooks/payments/{empty['provider'].lower()}/{world['t'].webhook_token}/"
    )
    with world["run"]():
        saved = world["owner"].put(URL, MOCK_KEYS, format="json")
    assert saved.json()["status"] == "CHECKING"
    shown = world["owner"].get(URL).json()
    assert (shown["status"], shown["provider"], shown["mode"]) == ("VERIFIED", "MOCK", "TEST")
    assert shown["saved"] == {
        "key_id": "••••_123",
        "key_secret": "••••4567",
        "webhook_secret": "••••8901",
    }
    assert "secret-4567" not in json.dumps(shown)
    with connection.cursor() as cursor:
        cursor.execute("SELECT key_secret, webhook_secret FROM payments_gatewayconfig")
        [(secret, hook)] = cursor.fetchall()
    assert "4567" not in secret and "8901" not in hook  # encrypted at rest
    with world["run"]():
        world["owner"].put(
            URL, {"provider": "MOCK", "mode": "TEST", "key_secret": "wrong"}, format="json"
        )
    failed = world["owner"].get(URL).json()
    assert (failed["status"], failed["last_error"]) == (
        "FAILED",
        "The gateway refused these keys.",
    )
    assert failed["saved"]["webhook_secret"] == "••••8901"  # blank fields kept
    with world["run"]():
        world["owner"].put(URL, {**MOCK_KEYS, "key_id": "", "webhook_secret": ""}, format="json")
        assert world["owner"].post(f"{URL}verify/").json()["status"] == "CHECKING"
    assert world["owner"].get(URL).json()["status"] == "VERIFIED"
    changed = [
        e.metadata["changed"]
        for e in AuditLog.objects.filter(action="payments.gateway_saved").order_by("created_at")
    ]
    assert changed == [["key_id", "key_secret", "webhook_secret"], ["key_secret"], ["key_secret"]]
    assert AuditLog.objects.filter(action="payments.gateway_checked").count() == 4


def test_what_is_refused_on_save(world, settings):
    payments_on(world["t"])
    live = world["owner"].put(URL, {**MOCK_KEYS, "mode": "LIVE"}, format="json")
    assert live.json()["error"]["details"]["fields"] == {
        "mode": ["Live payments aren't allowed here: use test keys."]
    }
    missing = world["owner"].put(URL, {"provider": "MOCK", "mode": "TEST"}, format="json")
    assert set(missing.json()["error"]["details"]["fields"]) == {
        "key_id",
        "key_secret",
        "webhook_secret",
    }
    razorpay = world["owner"].put(URL, {**MOCK_KEYS, "provider": "RAZORPAY"}, format="json")
    assert razorpay.json()["error"]["details"]["fields"] == {
        "key_id": ["A test key starts with rzp_test_."]
    }
    settings.ALLOW_MOCK_INTEGRATIONS = False
    assert world["owner"].put(URL, MOCK_KEYS, format="json").json()["error"]["details"][
        "fields"
    ] == {"provider": ["Choose a payment gateway."]}


def test_only_the_owner_and_each_business_its_own(world):
    payments_on(world["t"])
    payments_on(world["tb"])
    with world["run"]():
        world["owner"].put(URL, MOCK_KEYS, format="json")
    assert world["manager"].get(URL).status_code == 403
    theirs = world["other"].get(URL).json()
    assert (theirs["status"], theirs["saved"]["key_secret"]) == ("UNVERIFIED", "")
    assert world["tb"].webhook_token in theirs["webhook_url"]


def test_the_mock_gateways_signed_webhooks():
    gateway = MockGateway()
    order = gateway.create_order(KEYS, amount_paise=150000, receipt="r1", notes={"shop": "x"})
    body, headers = MockGateway.simulate(KEYS, order.order_id)
    event = gateway.parse_webhook(KEYS, body, headers)
    assert (event.kind, event.payment and event.payment.amount_paise) == (
        "PAYMENT_CAPTURED",
        150000,
    )
    assert event.event_id.startswith("evt_mock_")
    with pytest.raises(SignatureInvalid):
        gateway.parse_webhook(KEYS, body.replace(b"150000", b"1"), headers)
    other = GatewayKeys("MOCK", "TEST", "mock_key_123", "secret-4567", "another")
    with pytest.raises(SignatureInvalid):
        gateway.parse_webhook(other, body, headers)
    failed_body, failed_headers = MockGateway.simulate(KEYS, order.order_id, outcome="FAILED")
    assert gateway.parse_webhook(KEYS, failed_body, failed_headers).kind == "PAYMENT_FAILED"
    assert [p.status for p in gateway.order_payments(KEYS, order.order_id)] == [
        "CAPTURED",
        "FAILED",
    ]
    MockGateway.script("DOWN")
    with pytest.raises(GatewayError) as down:
        gateway.create_order(KEYS, amount_paise=100, receipt="r2", notes={})
    assert down.value.retryable


class FakeRazorpay:
    """Stands in for ``razorpay.Client``'s network calls; the signature helper stays real."""

    created: list[dict[str, Any]] = []
    real: Any = None  # the SDK's own Client, for its signature helper

    def __init__(self, auth: tuple[str, str]) -> None:
        self.auth = auth
        self.utility = FakeRazorpay.real(auth=auth).utility
        outer = self

        class Orders:
            def create(self, body: dict[str, Any]) -> dict[str, Any]:
                FakeRazorpay.created.append(body)
                return {"id": "order_rzp_1", "amount": body["amount"], "status": "created"}

            def all(self, params: dict[str, Any]) -> dict[str, Any]:
                import razorpay

                if outer.auth[1] == "bad":
                    raise razorpay.errors.BadRequestError("Authentication failed")
                return {"items": []}

            def payments(self, order_id: str) -> dict[str, Any]:
                return {
                    "items": [
                        {
                            "id": "pay_1",
                            "order_id": order_id,
                            "amount": 150000,
                            "status": "captured",
                            "method": "upi",
                            "created_at": 1790000000,
                        }
                    ]
                }

        self.order = Orders()


def test_razorpay_through_its_sdk(monkeypatch):
    import razorpay

    FakeRazorpay.real = razorpay.Client
    monkeypatch.setattr(razorpay, "Client", FakeRazorpay)
    keys = GatewayKeys("RAZORPAY", "TEST", "rzp_test_abc", "sec", "whsec")
    gateway = RazorpayGateway()
    gateway.verify(keys)
    with pytest.raises(GatewayError) as refused:
        gateway.verify(GatewayKeys("RAZORPAY", "TEST", "rzp_test_abc", "bad", "whsec"))
    assert refused.value.code == "AUTH_FAILED"
    order = gateway.create_order(keys, amount_paise=150000, receipt="PAY-1", notes={"a": "b"})
    assert order.order_id == "order_rzp_1"
    assert FakeRazorpay.created[-1] == {
        "amount": 150000,
        "currency": "INR",
        "receipt": "PAY-1",
        "notes": {"a": "b"},
    }
    body = json.dumps(
        {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_1",
                        "order_id": "order_rzp_1",
                        "amount": 150000,
                        "status": "captured",
                        "created_at": 1790000000,
                    }
                }
            },
        }
    ).encode()
    signature = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
    event = gateway.parse_webhook(
        keys, body, {"x-razorpay-signature": signature, "x-razorpay-event-id": "evt_1"}
    )
    assert (event.kind, event.event_id) == ("PAYMENT_CAPTURED", "evt_1")
    assert event.payment is not None and event.payment.captured_at is not None
    with pytest.raises(SignatureInvalid):
        gateway.parse_webhook(keys, body, {"x-razorpay-signature": "0" * 64})
    with pytest.raises(SignatureInvalid):
        gateway.parse_webhook(keys, body, {})
    [paid] = gateway.order_payments(keys, "order_rzp_1")
    assert (paid.status, paid.amount_paise) == ("CAPTURED", 150000)


def test_the_mock_is_refused_outside_dev(settings):
    assert isinstance(get_gateway("MOCK"), MockGateway)
    settings.ALLOW_MOCK_INTEGRATIONS = False
    with pytest.raises(ImproperlyConfigured):
        get_gateway("MOCK")
    with pytest.raises(ImproperlyConfigured):
        get_gateway("PAYPAL")


def test_staff_cant_record_an_online_payment_by_hand(tenant_a):
    shop = make_shop(tenant_a)
    staff = client_for(tenant_a, make_staff_in(tenant_a, "OWNER"))
    answer = staff.post(
        f"{API}/payments/",
        {
            "retailer": str(shop.pk),
            "amount": "100.00",
            "mode": "ONLINE",
            "payment_date": date.today().isoformat(),
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="online-by-hand-1",
    )
    assert answer.status_code == 400
    assert "mode" in answer.json()["error"]["details"]["fields"]
