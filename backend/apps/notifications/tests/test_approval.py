"""WhatsApp template approval (ADR-049 item 12): the super admin records the provider's answer; a
real provider sends only approved templates (the person's language, else English), everything
else is kept as "Not sent: template not approved" while in-app still goes; the rules editor can't
add WhatsApp where the template isn't approved and shows where it stands; editing an approved
text sends it back for approval; the mock sends everything as before."""

from typing import Any

import pytest

from apps.accounts.tests.factories import make_staff_in, make_super_admin
from apps.audit.models import AuditLog
from apps.inventory.tests.helpers import make_product
from apps.notifications import approval, quiet
from apps.notifications.adapters.whatsapp import MockWhatsAppClient
from apps.notifications.models import ApprovalStatus, Notification, PlatformTemplate
from apps.orders import transitions
from apps.orders.tests.helpers import add_stock, client_for, make_shop, place
from apps.platform import selectors
from apps.platform.models import FeatureFlag, TenantFeature
from apps.retailers.models import Retailer
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
API = "/api/v1"
SKIP = Notification.SkipReason


@pytest.fixture(autouse=True)
def _daytime(monkeypatch):
    monkeypatch.setattr(quiet, "current_hold", lambda now: None)
    MockWhatsAppClient.outbox.clear()


@pytest.fixture
def world(tenant_a, api_client_for, django_capture_on_commit_callbacks):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    with tenant_context(tenant_a.pk):
        Retailer.objects.filter(pk=shop.pk).update(whatsapp_opt_in=True)
        TenantFeature.objects.create(flag=FeatureFlag.objects.get(code="whatsapp"), enabled=True)
    selectors.invalidate_tenant_features(tenant_a.pk)
    product = make_product(tenant_a, "P-1")
    add_stock(tenant_a, product, "100")
    return {
        "t": tenant_a,
        "owner": owner,
        "shop": shop,
        "product": product,
        "staff": client_for(tenant_a, owner),
        "admin": api_client_for(make_super_admin()),
        "run": lambda: django_capture_on_commit_callbacks(execute=True),
    }


@pytest.fixture
def required(settings):
    settings.WHATSAPP_REQUIRE_APPROVED_TEMPLATES = True


def template(event: str = "order.accepted", audience: str = "SHOP", locale: str = "en"):
    return PlatformTemplate.objects.get(
        event_code=event, audience=audience, channel="WHATSAPP", locale=locale
    )


def mark(status: str, **key: Any) -> None:
    approval.set_approval(template(**key).pk, status, "" if status != "REJECTED" else "Wording")


def accepted(world: dict[str, Any]) -> dict[str, Notification]:
    with world["run"]():
        order = place(world["t"], world["shop"], (world["product"], "1"))
    with world["run"](), tenant_context(world["t"].pk):
        transitions.accept_order(order.pk, by=world["owner"])
    with tenant_context(world["t"].pk):
        rows = Notification.objects.filter(event_code="order.accepted")
        return {n.channel: n for n in rows.order_by("created_at")}


def test_the_mock_sends_templates_whatever_their_approval(world):
    assert template().approval_status == ApprovalStatus.NOT_SUBMITTED
    sent = accepted(world)["WHATSAPP"]
    assert (sent.status, sent.skip_reason) == ("SENT", "")
    assert [m.message.template for m in MockWhatsAppClient.outbox] == ["b2b_order_accepted"]


@pytest.mark.usefixtures("required")
def test_a_real_provider_sends_only_approved_templates(world):
    for status in ("NOT_SUBMITTED", "SUBMITTED", "REJECTED"):
        mark(status)
        found = accepted(world)
        assert (found["WHATSAPP"].status, found["WHATSAPP"].skip_reason) == (
            "SKIPPED",
            SKIP.NOT_APPROVED,
        )
        assert found["IN_APP"].status == "SENT"  # the other channels still go
        with tenant_context(world["t"].pk):
            Notification.objects.filter(event_code="order.accepted").delete()
    assert MockWhatsAppClient.outbox == []
    mark("APPROVED")
    assert accepted(world)["WHATSAPP"].status == "SENT"
    assert [m.message.template for m in MockWhatsAppClient.outbox] == ["b2b_order_accepted"]


@pytest.mark.usefixtures("required")
@pytest.mark.usefixtures("every_language")
def test_the_persons_language_when_approved_else_english(world):
    hindi = PlatformTemplate.objects.create(
        event_code="order.accepted",
        audience="SHOP",
        channel="WHATSAPP",
        locale="hi",
        body="{{ distributor }}: आपका ऑर्डर {{ order_number }} स्वीकार हो गया।",
        whatsapp_template_name="b2b_order_accepted",
        whatsapp_language="hi",
        whatsapp_category="UTILITY",
        variables=["distributor", "order_number"],
    )
    with tenant_context(world["t"].pk):
        Retailer.objects.filter(pk=world["shop"].pk).update(preferred_language="hi")
    mark("APPROVED")
    english = accepted(world)["WHATSAPP"]
    assert english.status == "SENT"
    assert english.data["whatsapp"]["language"] == "en"
    assert "स्वीकार" not in english.body
    with tenant_context(world["t"].pk):
        Notification.objects.filter(event_code="order.accepted").delete()
    approval.set_approval(hindi.pk, "APPROVED")
    in_hindi = accepted(world)["WHATSAPP"]
    assert in_hindi.data["whatsapp"]["language"] == "hi"
    assert "स्वीकार" in in_hindi.body


@pytest.mark.usefixtures("required")
def test_the_rules_editor_adds_whatsapp_only_where_approved(world):
    matrix = world["staff"].get(f"{API}/notification-rules/").json()
    assert matrix["whatsapp_approval_required"] is True
    placed = next(e for e in matrix["events"] if e["code"] == "order.placed")
    assert {(t["audience"], t["status"], t["ready"]) for t in placed["whatsapp"]["templates"]} == {
        ("SHOP", "NOT_SUBMITTED", False),
        ("STAFF", "NOT_SUBMITTED", False),
    }
    shop_rule = {"recipient": "SHOP", "channels": ["IN_APP", "WHATSAPP"]}
    refused = world["staff"].put(
        f"{API}/notification-rules/order.placed/", {"rules": [shop_rule]}, format="json"
    )
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"]["rules"] == [
        "This message's WhatsApp template isn't approved yet."
    ]
    # A rule already using WhatsApp can still be edited (the editor warns about it instead).
    kept = world["staff"].put(
        f"{API}/notification-rules/order.accepted/",
        {"rules": [{"recipient": "SHOP", "channels": ["IN_APP", "WHATSAPP", "EMAIL"]}]},
        format="json",
    )
    assert kept.status_code == 200
    mark("APPROVED", event="order.placed")
    matrix = world["staff"].get(f"{API}/notification-rules/").json()
    placed = next(e for e in matrix["events"] if e["code"] == "order.placed")
    shop_template = next(t for t in placed["whatsapp"]["templates"] if t["audience"] == "SHOP")
    assert (shop_template["status"], shop_template["ready"]) == ("APPROVED", True)
    added = world["staff"].put(
        f"{API}/notification-rules/order.placed/", {"rules": [shop_rule]}, format="json"
    )
    assert added.status_code == 200


def test_with_the_mock_every_template_is_ready_in_the_editor(world):
    matrix = world["staff"].get(f"{API}/notification-rules/").json()
    assert matrix["whatsapp_approval_required"] is False
    assert all(
        t["ready"] and t["status"] == "NOT_SUBMITTED"
        for e in matrix["events"]
        for t in e["whatsapp"]["templates"]
    )


@covers("platform-notification-template-approval")
def test_the_super_admin_records_approval(world):
    admin, row = world["admin"], template()
    url = f"{API}/platform/notification-templates/{row.pk}/approval/"
    saved = admin.post(url, {"status": "SUBMITTED"}, format="json")
    assert saved.status_code == 200
    assert (saved.json()["approval_status"], saved.json()["approval_changed_at"] is not None) == (
        "SUBMITTED",
        True,
    )
    no_reason = admin.post(url, {"status": "REJECTED"}, format="json")
    assert no_reason.status_code == 400
    assert "note" in no_reason.json()["error"]["details"]["fields"]
    rejected = admin.post(url, {"status": "REJECTED", "note": "Promotional wording"}, format="json")
    assert (rejected.json()["approval_status"], rejected.json()["approval_note"]) == (
        "REJECTED",
        "Promotional wording",
    )
    log = AuditLog.objects.filter(action="notifications.template_approval_changed")
    assert [entry.changes["approval_status"] for entry in log.order_by("created_at")] == [
        ["NOT_SUBMITTED", "SUBMITTED"],
        ["SUBMITTED", "REJECTED"],
    ]
    assert all(entry.tenant_id is None for entry in log)
    in_app = PlatformTemplate.objects.get(
        event_code="order.accepted", audience="SHOP", channel="IN_APP", locale="en"
    )
    not_whatsapp = admin.post(
        f"{API}/platform/notification-templates/{in_app.pk}/approval/",
        {"status": "APPROVED"},
        format="json",
    )
    assert not_whatsapp.status_code == 400
    missing = admin.post(
        f"{API}/platform/notification-templates/{world['owner'].pk}/approval/",
        {"status": "APPROVED"},
        format="json",
    )
    assert missing.status_code == 404
    assert world["staff"].post(url, {"status": "APPROVED"}, format="json").status_code == 403
    assert template().approval_status == ApprovalStatus.REJECTED


def test_changing_an_approved_text_sends_it_back_for_approval(world):
    admin = world["admin"]
    mark("APPROVED")
    url = f"{API}/platform/notification-templates/order.accepted/WHATSAPP/"
    same = {"body": template().body}
    assert admin.put(url, same, format="json").json()["approval_status"] == "APPROVED"
    changed = admin.put(
        url, {"body": "{{ distributor }}: order {{ order_number }} is accepted."}, format="json"
    ).json()
    assert (changed["approval_status"], changed["approval_note"]) == (
        "NOT_SUBMITTED",
        approval.TEXT_CHANGED_NOTE,
    )
    entry = AuditLog.objects.filter(action="notifications.platform_template_changed").latest(
        "created_at"
    )
    assert entry.changes["approval_status"] == ["APPROVED", "NOT_SUBMITTED"]
