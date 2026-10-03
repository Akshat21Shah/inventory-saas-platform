"""Editing message texts (ADR-048 item 14): a distributor's own in-app and email texts are used
and can be reset; only the event's variables are accepted; WhatsApp and SMS texts are the
platform's; the preview fills sample values; every change is audited."""

from decimal import Decimal as D

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.inventory.tests.helpers import make_product
from apps.notifications import texts
from apps.notifications.models import Notification, PlatformTemplate
from apps.notifications.texts import TextInput, WhatsAppFields
from apps.orders.tests.helpers import add_stock, make_shop, place
from common.errors import InvalidFields, NotFound
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


def own(body: str = "{{ shop }} ordered {{ total }}", **kw) -> TextInput:
    fields = {
        "event_code": "order.placed",
        "channel": "IN_APP",
        "locale": "en",
        "subject": "Order {{ order_number }}",
        "body": body,
    } | kw
    return TextInput(**fields)


def test_a_distributors_text_is_used_until_it_is_reset(
    tenant_a, django_capture_on_commit_callbacks
):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    product = make_product(tenant_a, "P-1", base_price=D("10"))
    add_stock(tenant_a, product, "10")
    with tenant_context(tenant_a.pk):
        texts.save_tenant_text(own(audience="STAFF"))  # the office's words
        assert AuditLog.objects.filter(action="notifications.template_changed").exists()
        shown = {
            t["audience"]: t for t in texts.texts_for("order.placed") if t["channel"] == "IN_APP"
        }
        assert (shown["STAFF"]["source"], shown["STAFF"]["editable"]) == ("tenant", True)
        assert shown["SHOP"]["source"] == "platform"
    with django_capture_on_commit_callbacks(execute=True):
        order = place(tenant_a, shop, (product, "1"))
    with tenant_context(tenant_a.pk):
        mine = Notification.objects.get(event_code="order.placed", recipient=owner)
        assert (mine.title, mine.body) == (
            f"Order {order.number}",
            f"{shop.shop_name} ordered ₹{order.grand_total}",
        )
        theirs = Notification.objects.get(event_code="order.placed", recipient__phone=shop.mobile)
        assert theirs.title == f"Order {order.number} placed"  # the shop's platform text
        assert not texts.reset_tenant_text("order.placed", "IN_APP", "en", "SHOP")
        assert texts.reset_tenant_text("order.placed", "IN_APP", "en", "STAFF")
        assert AuditLog.objects.filter(action="notifications.template_reset").exists()
        shown = {
            t["audience"]: t for t in texts.texts_for("order.placed") if t["channel"] == "IN_APP"
        }
        assert shown["STAFF"]["source"] == "platform"


def test_only_known_variables_and_plain_placeholders(tenant_a):
    with tenant_context(tenant_a.pk):
        with pytest.raises(InvalidFields) as unknown:
            texts.save_tenant_text(own("{{ shop }} owes {{ secret_key }}"))
        [message] = unknown.value.details["fields"]["body"]
        assert "secret_key" in message and "{{ order_number }}" in message
        with pytest.raises(InvalidFields):
            texts.save_tenant_text(own("{% if 1 %}hi{% endif %}"))
        with pytest.raises(InvalidFields) as channel:
            texts.save_tenant_text(own(channel="WHATSAPP"))
        assert "channel" in channel.value.details["fields"]
        with pytest.raises(InvalidFields):
            texts.save_tenant_text(own(subject=" "))
        with pytest.raises(InvalidFields):
            texts.save_tenant_text(own(locale="fr"))
        with pytest.raises(NotFound):
            texts.save_tenant_text(own(event_code="order.teleported"))
        with pytest.raises(InvalidFields) as audience:  # announcements only go to shops
            texts.save_tenant_text(
                own("{{ message }}", event_code="announcement.published", audience="STAFF")
            )
        assert "audience" in audience.value.details["fields"]
        with pytest.raises(InvalidFields):  # document links only go to shops
            texts.save_tenant_text(
                own("{{ document_link }}", event_code="invoice.issued", audience="STAFF")
            )
        staff_variables = next(
            t["variables"]
            for t in texts.texts_for("invoice.issued")
            if t["audience"] == "STAFF" and t["channel"] == "IN_APP"
        )
        assert "document_link" not in staff_variables
        with pytest.raises(InvalidFields):  # stock alerts only go to staff
            texts.save_tenant_text(
                own("{{ product }}", event_code="stock.alert_opened", audience="SHOP")
            )


def test_the_preview_fills_sample_values(tenant_a):
    with tenant_context(tenant_a.pk):
        shown = texts.preview(own("{{ distributor }}: {{ shop }} ordered {{ total }}"), "Alpha")
    assert shown == {
        "subject": "Order ORD-2026-000123",
        "body": "Alpha: Ganesh Kirana ordered ₹12,450.00",
    }


def test_the_super_admin_sets_the_whatsapp_text_and_its_approved_template(tenant_a):
    data = TextInput(
        "order.accepted",
        "WHATSAPP",
        "en",
        "",
        "{{ distributor }}: order {{ order_number }} accepted ({{ total }}). {{ document_link }}",
    )
    row = texts.save_platform_text(data, WhatsAppFields("b2b_order_accepted_v2", "en", ""))
    assert row.whatsapp_template_name == "b2b_order_accepted_v2"
    assert row.whatsapp_category == "UTILITY"  # kept from the seed
    assert row.variables == ["distributor", "order_number", "total", "document_link"]
    entry = AuditLog.objects.get(action="notifications.platform_template_changed")
    assert entry.tenant_id is None
    with pytest.raises(InvalidFields):
        texts.save_platform_text(data, WhatsAppFields(category="PROMO"))
    assert (
        PlatformTemplate.objects.filter(
            event_code="order.accepted", audience="SHOP", channel="WHATSAPP", locale="en"
        ).count()
        == 1
    )
    with tenant_context(tenant_a.pk):
        found = [t for t in texts.texts_for("order.accepted") if t["channel"] == "WHATSAPP"]
    assert {t["audience"] for t in found} == {"SHOP", "STAFF"}
    shop_wa = next(t for t in found if t["audience"] == "SHOP")
    assert (shop_wa["source"], shop_wa["editable"]) == ("platform", False)
    assert shop_wa["body"].startswith("{{ distributor }}: order {{ order_number }} accepted")
