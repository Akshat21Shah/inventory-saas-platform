"""Notification APIs (PLAN §3.11): the inbox and badge (own messages only), preferences, rules,
texts with preview, the delivery log with retry, announcements, document links, reminder pauses,
WhatsApp consent, the GST card, the shop's side and the super admin's; roles; and another
tenant seeing and changing nothing on every route."""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.accounts.tests.factories import make_staff_in, make_super_admin
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.notifications import quiet
from apps.notifications.adapters.base import DeliveryError
from apps.notifications.adapters.whatsapp import MockWhatsAppClient
from apps.notifications.models import DocumentLink, Notification
from apps.orders.tests.helpers import add_stock, client_for, make_shop, shop_client
from apps.platform import selectors
from apps.platform.models import FeatureFlag, TenantFeature
from apps.retailers.models import Retailer
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"


@pytest.fixture(autouse=True)
def _daytime(monkeypatch):
    monkeypatch.setattr(quiet, "current_hold", lambda now: None)
    MockWhatsAppClient.outbox.clear()


@pytest.fixture
def world(tenant_a, tenant_b, django_capture_on_commit_callbacks):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a, email="shop@example.com")
    with tenant_context(tenant_a.pk):
        Retailer.objects.filter(pk=shop.pk).update(whatsapp_opt_in=True)
        TenantFeature.objects.create(flag=FeatureFlag.objects.get(code="whatsapp"), enabled=True)
    selectors.invalidate_tenant_features(tenant_a.pk)
    product = make_product(tenant_a, "P-1")
    add_stock(tenant_a, product, "100")
    run = django_capture_on_commit_callbacks
    with run(execute=True):
        bill = ship_invoice(tenant_a, shop, owner, (product, "2"))
    other_owner = make_staff_in(tenant_b, "OWNER")
    other_shop = make_shop(tenant_b, "9876500099")
    return {
        "t": tenant_a,
        "owner": owner,
        "shop": shop,
        "bill": bill,
        "product": product,
        "staff": client_for(tenant_a, owner),
        "sales": client_for(tenant_a, make_staff_in(tenant_a, "SALES")),
        "shop_api": shop_client(tenant_a, shop),
        "other": client_for(tenant_b, other_owner),
        "other_shop": other_shop,
        "run": run,
    }


def one(world: dict[str, Any], **filters: Any) -> Notification:
    with tenant_context(world["t"].pk):
        found: Notification = Notification.objects.filter(**filters).latest("created_at")
        return found


@covers(
    "notifications",
    "notifications-unread",
    "notification-read",
    "notifications-read-all",
    "shop-notifications",
    "shop-notifications-unread",
    "shop-notification-read",
    "shop-notifications-read-all",
)
def test_each_person_reads_only_their_own_messages(world):
    shop_api, staff, other = world["shop_api"], world["staff"], world["other"]
    count = shop_api.get(f"{API}/shop/notifications/unread-count/").json()["unread"]
    assert count >= 2  # order accepted, bill
    page = shop_api.get(f"{API}/shop/notifications/?unread=true").json()
    titles = [n["title"] for n in page["results"]]
    assert any(world["bill"].number in t for t in titles)
    first = page["results"][0]
    assert first["path"].startswith("/shop/") and first["is_read"] is False
    assert other.get(f"{API}/notifications/").json()["results"] == []
    assert other.post(f"{API}/notifications/{first['id']}/read/").status_code == 404
    assert staff.post(f"{API}/notifications/{first['id']}/read/").status_code == 404  # not his
    assert shop_api.post(f"{API}/shop/notifications/{first['id']}/read/").json() == {"marked": 1}
    assert shop_api.get(f"{API}/shop/notifications/unread-count/").json()["unread"] == count - 1
    shop_api.post(f"{API}/shop/notifications/read-all/")
    assert shop_api.get(f"{API}/shop/notifications/unread-count/").json()["unread"] == 0
    assert staff.get(f"{API}/shop/notifications/").status_code == 403
    assert shop_api.get(f"{API}/notifications/").status_code == 403
    staff_count = staff.get(f"{API}/notifications/unread-count/").json()["unread"]
    assert staff_count >= 1  # the order was placed
    staff.post(f"{API}/notifications/read-all/")
    assert staff.get(f"{API}/notifications/unread-count/").json() == {"unread": 0}
    assert other.get(f"{API}/notifications/unread-count/").json() == {"unread": 0}


@covers("notification-preferences", "shop-notification-preferences")
def test_preferences(world):
    shop_api = world["shop_api"]
    rows = {r["event"]: r for r in shop_api.get(f"{API}/shop/notification-preferences/").json()}
    assert rows["invoice.issued"]["compulsory"]
    body = {"event": "order.accepted", "channel": "WHATSAPP", "enabled": False}
    changed = shop_api.put(f"{API}/shop/notification-preferences/", body, format="json")
    assert changed.status_code == 200
    locked = {"event": "invoice.issued", "channel": "EMAIL", "enabled": False}
    refused = shop_api.put(f"{API}/shop/notification-preferences/", locked, format="json")
    assert refused.status_code == 400
    staff_rows = world["staff"].get(f"{API}/notification-preferences/").json()
    assert "order.placed" in {r["event"] for r in staff_rows}
    staff_body = {"event": "order.placed", "channel": "IN_APP", "enabled": False}
    assert (
        world["staff"]
        .put(f"{API}/notification-preferences/", staff_body, format="json")
        .status_code
        == 400
    )
    other = world["other"].get(f"{API}/notification-preferences/").json()
    assert {r["event"] for r in other} == {r["event"] for r in staff_rows}  # its own, from rules


@covers("notification-rules", "notification-rule")
def test_rules_matrix_changes_and_reset(world):
    staff, other = world["staff"], world["other"]
    matrix = staff.get(f"{API}/notification-rules/").json()
    invoice = next(e for e in matrix["events"] if e["code"] == "invoice.issued")
    assert invoice["whatsapp"]["enabled"] and invoice["whatsapp"]["messages_30_days"] == 1
    assert invoice["whatsapp"]["price"] is None and invoice["whatsapp"]["cost_30_days"] is None
    assert matrix["prices_set"] is False and matrix["shops"] == {"opted_in": 1, "shops": 1}
    codes = {p["code"] for p in matrix["permissions"]}
    assert "orders.manage" in codes and not any(c.startswith("platform.") for c in codes)
    assert world["sales"].get(f"{API}/notification-rules/").status_code == 403
    body = {
        "rules": [
            {"recipient": "SHOP", "channels": ["IN_APP", "EMAIL"], "compulsory": True},
            {"recipient": "OWNERS", "channels": ["IN_APP"]},
        ]
    }
    saved = staff.put(f"{API}/notification-rules/invoice.issued/", body, format="json")
    assert saved.status_code == 200, saved.json()
    assert {r["recipient"] for r in saved.json() if r["enabled"]} == {"SHOP", "OWNERS"}
    shops_only = {"rules": [{"recipient": "OWNERS", "channels": ["IN_APP"]}]}
    refused = staff.put(f"{API}/notification-rules/retailer.welcome/", shops_only, format="json")
    assert "This message is for shops only." in str(refused.json())
    bad = {"rules": [{"recipient": "OWNERS", "channels": ["SMS"]}]}
    assert (
        staff.put(f"{API}/notification-rules/invoice.issued/", bad, format="json").status_code
        == 400
    )
    other_matrix = other.get(f"{API}/notification-rules/").json()
    other_invoice = next(e for e in other_matrix["events"] if e["code"] == "invoice.issued")
    assert not other_invoice["customised"]  # tenant A's change stays in tenant A
    reset = staff.delete(f"{API}/notification-rules/invoice.issued/")
    assert all(r["is_default"] for r in reset.json())


@covers("notification-templates", "notification-template", "notification-template-preview")
def test_texts_and_preview(world):
    staff, other = world["staff"], world["other"]
    texts = staff.get(f"{API}/notification-templates/order.placed/").json()
    assert {t["channel"] for t in texts} >= {"IN_APP"}
    body = {"subject": "Order {{ order_number }}", "body": "{{ shop }} ordered"}
    saved = staff.put(f"{API}/notification-templates/order.placed/IN_APP/", body, format="json")
    in_app = next(t for t in saved.json() if t["channel"] == "IN_APP")
    assert in_app["source"] == "tenant"
    assert (
        staff.put(
            f"{API}/notification-templates/order.placed/WHATSAPP/", body, format="json"
        ).status_code
        == 400
    )
    other_texts = other.get(f"{API}/notification-templates/order.placed/").json()
    assert next(t for t in other_texts if t["channel"] == "IN_APP")["source"] == "platform"
    preview = staff.post(
        f"{API}/notification-templates/preview/",
        {"event": "order.placed", "channel": "IN_APP", **body},
        format="json",
    ).json()
    assert preview == {"subject": "Order ORD-2026-000123", "body": "Ganesh Kirana ordered"}
    reset = staff.delete(f"{API}/notification-templates/order.placed/IN_APP/?locale=en")
    assert next(t for t in reset.json() if t["channel"] == "IN_APP")["source"] == "platform"
    # Both audiences: the shop's words and the office's, each editable on its own.
    audiences = {(t["audience"], t["channel"]) for t in texts}
    assert {("SHOP", "IN_APP"), ("STAFF", "IN_APP"), ("STAFF", "EMAIL")} <= audiences
    office = {**body, "audience": "STAFF", "body": "{{ shop }} ordered {{ total }}"}
    saved = staff.put(f"{API}/notification-templates/order.placed/IN_APP/", office, format="json")
    by_audience = {t["audience"]: t for t in saved.json() if t["channel"] == "IN_APP"}
    assert (by_audience["STAFF"]["source"], by_audience["SHOP"]["source"]) == ("tenant", "platform")
    reset = staff.delete(
        f"{API}/notification-templates/order.placed/IN_APP/?locale=en&audience=STAFF"
    )
    by_audience = {t["audience"]: t for t in reset.json() if t["channel"] == "IN_APP"}
    assert by_audience["STAFF"]["source"] == "platform"
    bad = staff.delete(f"{API}/notification-templates/order.placed/IN_APP/?audience=BOTH")
    assert bad.status_code == 400
    assert staff.get(f"{API}/notification-templates/order.teleported/").status_code == 404


@covers(
    "notification-deliveries",
    "notification-delivery-counts",
    "notification-delivery",
    "notification-delivery-retry",
)
def test_delivery_log_and_retry(world, monkeypatch):
    staff, other = world["staff"], world["other"]

    def broken(self, message, sender):
        from apps.notifications.adapters.base import PermanentDeliveryError

        raise PermanentDeliveryError("number not on WhatsApp")

    monkeypatch.setattr(MockWhatsAppClient, "send_template", broken)
    with world["run"](execute=True):
        ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "1"))
    failed = staff.get(f"{API}/notification-deliveries/?status=FAILED").json()["results"]
    assert failed and all(r["channel"] == "WHATSAPP" for r in failed)
    row = failed[0]
    assert row["last_error"] == "number not on WhatsApp" and row["shop_name"]
    detail = staff.get(f"{API}/notification-deliveries/{row['id']}/").json()
    assert detail["delivery_attempts"][0]["status"] == "FAILED"
    assert staff.get(f"{API}/notification-deliveries/counts/").json()["FAILED"] >= 1
    assert other.get(f"{API}/notification-deliveries/").json()["results"] == []
    assert other.get(f"{API}/notification-deliveries/{row['id']}/").status_code == 404
    assert other.post(f"{API}/notification-deliveries/{row['id']}/retry/").status_code == 404
    monkeypatch.undo()
    MockWhatsAppClient.outbox.clear()
    with world["run"](execute=True):
        retried = staff.post(f"{API}/notification-deliveries/{row['id']}/retry/")
    assert retried.status_code == 200
    assert one(world, pk=row["id"]).status == "SENT"
    again = staff.post(f"{API}/notification-deliveries/{row['id']}/retry/")
    assert again.status_code == 400
    assert world["sales"].get(f"{API}/notification-deliveries/").status_code == 403
    assert staff.get(f"{API}/notification-deliveries/?status=LOST").status_code == 400


@covers("announcements", "announcement", "shop-announcements")
def test_announcements(world):
    staff, other = world["staff"], world["other"]
    body = {
        "title": "Diwali timings",
        "body": "Orders after 2 PM go the next day.",
        "starts_at": (timezone.now() - timedelta(minutes=1)).isoformat(),
    }
    created = staff.post(f"{API}/announcements/", body, format="json")
    assert created.status_code == 201, created.json()
    pk = created.json()["id"]
    shown = world["shop_api"].get(f"{API}/shop/announcements/").json()
    assert [a["title"] for a in shown] == ["Diwali timings"]
    other_shop = shop_client(_tenant_b(), world["other_shop"])
    assert other_shop.get(f"{API}/shop/announcements/").json() == []
    assert other.get(f"{API}/announcements/{pk}/").status_code == 404
    assert other.put(f"{API}/announcements/{pk}/", body, format="json").status_code == 404
    assert other.get(f"{API}/announcements/").json()["results"] == []
    ended = staff.put(f"{API}/announcements/{pk}/", {**body, "is_active": False}, format="json")
    assert ended.json()["is_active"] is False
    assert world["shop_api"].get(f"{API}/shop/announcements/").json() == []
    assert world["sales"].post(f"{API}/announcements/", body, format="json").status_code == 403


def _tenant_b() -> Any:
    from apps.platform.models import Tenant

    return Tenant.objects.get(slug="bravo")


@covers("document-links", "document-links-revoke")
def test_document_links_listed_and_revoked(world):
    staff, other = world["staff"], world["other"]
    ref = {"kind": "INVOICE", "object_id": str(world["bill"].pk)}
    listed = staff.get(f"{API}/document-links/", ref).json()
    assert len(listed) == 1 and listed[0]["is_live"]
    assert other.get(f"{API}/document-links/", ref).json() == []
    assert other.post(f"{API}/document-links/revoke/", ref, format="json").status_code == 404
    assert (
        world["sales"].post(f"{API}/document-links/revoke/", ref, format="json").status_code == 403
    )
    assert staff.post(f"{API}/document-links/revoke/", ref, format="json").json() == {"revoked": 1}
    with tenant_context(world["t"].pk):
        assert DocumentLink.objects.get(kind="INVOICE").revoked_at is not None


@covers("retailer-reminder-pause")
def test_reminder_pause(world):
    staff, other = world["staff"], world["other"]
    url = f"{API}/retailers/{world['shop'].pk}/reminder-pause/"
    assert staff.get(url).json() == {"pause": None}
    paused = staff.post(url, {"reason": "Disputed bill"}, format="json").json()
    assert paused["pause"]["reason"] == "Disputed bill"
    assert other.get(url).status_code == 404
    assert other.delete(url).status_code == 404
    assert world["sales"].post(url, {"reason": "x"}, format="json").status_code == 403
    assert staff.delete(url).json() == {"pause": None}


@covers("retailer-whatsapp-consent", "shop-whatsapp-consent", "shop-whatsapp-consent-prompted")
def test_whatsapp_consent_from_staff_and_the_shop(world):
    staff, other, shop_api = world["staff"], world["other"], world["shop_api"]
    url = f"{API}/retailers/{world['shop'].pk}/whatsapp-consent/"
    assert staff.get(url).json()["opted_in"] is True
    assert staff.put(url, {"agreed": False}, format="json").json()["opted_in"] is False
    unconfirmed = staff.put(url, {"agreed": True}, format="json")
    assert unconfirmed.status_code == 400
    confirmed = staff.put(url, {"agreed": True, "confirmed": True}, format="json").json()
    assert confirmed["opted_in"] and confirmed["source"] == "STAFF"
    assert other.get(url).status_code == 404
    assert other.put(url, {"agreed": False, "confirmed": True}, format="json").status_code == 404
    state = shop_api.get(f"{API}/shop/whatsapp-consent/").json()
    assert state["opted_in"] and state["whatsapp_available"] and not state["prompt"]
    off = shop_api.put(f"{API}/shop/whatsapp-consent/", {"agreed": False}, format="json").json()
    assert off["opted_in"] is False and off["prompt"] is False  # answered: not asked again
    shop_api.post(f"{API}/shop/whatsapp-consent/prompted/")
    other_state = shop_client(_tenant_b(), world["other_shop"]).get(f"{API}/shop/whatsapp-consent/")
    assert other_state.json()["prompt"] is True  # its own state, untouched


@covers("tax-upcoming-rate-changes")
def test_upcoming_rate_changes_card(world):
    from decimal import Decimal as D

    from apps.catalog.models import ProductTaxRate
    from common.dates import today_ist

    with tenant_context(world["t"].pk):
        ProductTaxRate.objects.create(
            product=world["product"], gst_rate=D("12"), effective_from=today_ist() + timedelta(10)
        )
    [change] = world["staff"].get(f"{API}/tax/upcoming-rate-changes/").json()
    assert (change["code"], change["new_rate"]) == ("P-1", "12.000")
    assert world["other"].get(f"{API}/tax/upcoming-rate-changes/").json() == []


@covers(
    "platform-notification-templates",
    "platform-notification-template",
    "platform-notification-template-preview",
    "platform-notification-failures",
    "platform-notification-failure-retry",
)
def test_super_admin_texts_and_failures(world, api_client_for, monkeypatch):
    admin = api_client_for(make_super_admin())
    listed = admin.get(f"{API}/platform/notification-templates/?event=order.accepted").json()
    assert {t["channel"] for t in listed} >= {"IN_APP", "WHATSAPP"}
    submission = {(t["audience"], t["channel"]): t["submitted_by_default"] for t in listed}
    assert submission[("SHOP", "WHATSAPP")] is True
    assert submission[("STAFF", "WHATSAPP")] is False  # optional, not submitted by default
    assert submission[("SHOP", "IN_APP")] is None
    handover = admin.get(f"{API}/platform/notification-templates/?event=handover.reminder").json()
    assert next(t for t in handover if t["channel"] == "WHATSAPP")["submitted_by_default"] is True
    body = {
        "subject": "",
        "body": "{{ distributor }}: order {{ order_number }} accepted. {{ document_link }}",
        "whatsapp_template_name": "b2b_order_accepted_v2",
    }
    saved = admin.put(
        f"{API}/platform/notification-templates/order.accepted/WHATSAPP/", body, format="json"
    ).json()
    assert saved["variables"] == ["distributor", "order_number", "document_link"]
    assert saved["audience"] == "SHOP"
    office = admin.put(
        f"{API}/platform/notification-templates/order.accepted/WHATSAPP/",
        {
            "audience": "STAFF",
            "body": "{{ distributor }}: {{ shop }}'s order {{ order_number }} ok",
        },
        format="json",
    ).json()
    assert (office["audience"], office["whatsapp_template_name"]) == (
        "STAFF",
        "b2b_order_accepted_staff",
    )
    preview = admin.post(
        f"{API}/platform/notification-templates/preview/",
        {"event": "order.accepted", "channel": "WHATSAPP", **body},
        format="json",
    ).json()
    assert preview["body"].startswith("Sharma Distributors: order ORD-2026-000123")
    assert world["staff"].get(f"{API}/platform/notification-templates/").status_code == 403

    def broken(self, message, sender):
        raise DeliveryError("down")

    monkeypatch.setattr("apps.notifications.delivery.MAX_ATTEMPTS", 1)
    monkeypatch.setattr(MockWhatsAppClient, "send_template", broken)
    with world["run"](execute=True):
        ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "1"))
    failures = admin.get(f"{API}/platform/notification-failures/").json()["results"]
    assert failures and failures[0]["tenant_name"] == world["t"].name
    assert failures[0]["recipient_name"] == ""
    filtered = admin.get(
        f"{API}/platform/notification-failures/?tenant={world['other_shop'].tenant_id}"
    ).json()
    assert filtered["results"] == []
    assert world["staff"].get(f"{API}/platform/notification-failures/").status_code == 403
    monkeypatch.undo()
    with world["run"](execute=True):
        retried = admin.post(f"{API}/platform/notification-failures/{failures[0]['id']}/retry/")
    assert retried.status_code == 200
    assert one(world, pk=failures[0]["id"]).status == "SENT"
