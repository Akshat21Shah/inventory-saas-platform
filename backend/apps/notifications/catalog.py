# ruff: noqa: E501 - the default texts are data, one line per text
"""The notification catalogue (ADR-048, PLAN §10.2h): every event a distributor can configure,
how urgent it is, its WhatsApp category, the variables its templates may use, the document it
links, and the platform's default rules and English templates.

Notification events are the outbox events, split where the default depends on context (placed by
staff, cancelled by the shop, a bounced cheque, dispatch after an earlier invoice): see
``apps.notifications.consumer.notification_code``.

Every WhatsApp and SMS text names the distributor first ("{{ distributor }}: …"), because one
platform number sends for every distributor.
"""

import re
from dataclasses import dataclass, field

from apps.notifications.models import Audience, Channel, DocumentLink, Recipient, WhatsAppCategory

IN, EM, WA, SMS = Channel.IN_APP, Channel.EMAIL, Channel.WHATSAPP, Channel.SMS
UTILITY, MARKETING = WhatsAppCategory.UTILITY, WhatsAppCategory.MARKETING


@dataclass(frozen=True)
class Event:
    code: str
    label: str  # for the rules screen
    group: str  # orders, backorders, stock, billing, payments, reminders, other
    urgent: bool = True  # False: WhatsApp, SMS and email wait for quiet hours to end
    category: str = UTILITY  # WhatsApp price category
    variables: tuple[str, ...] = ()
    document: str = ""  # DocumentLink.Kind the message links, if any
    shop_facing: bool = True  # the shop can be a recipient
    staff_facing: bool = True  # staff can be recipients (not: the welcome, announcements)
    supplier_facing: bool = False  # the supplier, by email (purchase orders, ADR-053)
    feature: str = ""  # an optional module's flag: the event is hidden while it is off
    # A personal system message ("Report ready"): fixed rules, never on the rules, texts or
    # preferences screens (ADR-050).
    system: bool = False

    @property
    def audiences(self) -> tuple[str, ...]:
        return tuple(
            audience
            for audience, reached in (
                (Audience.SHOP, self.shop_facing),
                (Audience.STAFF, self.staff_facing),
                (Audience.SUPPLIER, self.supplier_facing),
            )
            if reached
        )


_ORDER = ("distributor", "shop", "order_number", "total", "link")
EVENTS: dict[str, Event] = {
    e.code: e
    for e in (
        Event("order.placed", "New order from a shop", "orders", variables=_ORDER),
        Event("order.placed_for_shop", "Order placed by staff for a shop", "orders",
              variables=(*_ORDER, "placed_by")),
        Event("order.on_hold", "Order waiting for credit approval", "orders",
              variables=(*_ORDER, "hold_reason")),
        Event("order.hold_approved", "Credit hold approved", "orders", variables=_ORDER),
        Event("order.accepted", "Order accepted", "orders",
              variables=(*_ORDER, "document_link"), document=DocumentLink.Kind.ORDER_CONFIRMATION),
        Event("order.rejected", "Order rejected", "orders", variables=(*_ORDER, "reason")),
        Event("order.cancelled", "Order cancelled by staff", "orders",
              variables=(*_ORDER, "reason")),
        Event("order.cancelled_by_shop", "Order cancelled by the shop", "orders",
              variables=_ORDER, shop_facing=False),
        Event("order.modified", "Order changed before acceptance", "orders",
              variables=(*_ORDER, "changes")),
        Event("order.short_supplied", "Less supplied than ordered", "orders",
              variables=(*_ORDER, "items")),
        Event("order.dispatched", "Order dispatched (the invoice goes with it)", "orders",
              variables=(*_ORDER, "shipment", "vehicle")),
        Event("order.dispatched_after_invoice", "Order dispatched (invoiced earlier)", "orders",
              variables=(*_ORDER, "shipment", "vehicle", "transporter", "lr_number")),
        Event("order.delivered", "Order delivered", "orders", variables=(*_ORDER, "shipment")),
        Event("order.completed", "Order complete", "orders", variables=_ORDER),
        Event("backorder.proposed", "Arriving stock ready to allocate", "backorders",
              variables=(*_ORDER, "product", "quantity"), shop_facing=False),
        Event("backorder.allocated", "Waiting items on their way", "backorders",
              variables=(*_ORDER, "shipment", "price_increased")),
        Event("backorder.skipped_credit", "Waiting items held: shop over its credit",
              "backorders", variables=(*_ORDER, "product", "quantity"), shop_facing=False),
        Event("backorder.skipped_blocked", "Waiting items held: shop blocked", "backorders",
              variables=(*_ORDER, "product", "quantity"), shop_facing=False),
        Event("backorder.cancelled", "Waiting items cancelled by staff", "backorders",
              variables=(*_ORDER, "product", "quantity")),
        Event("backorder.cancelled_by_shop", "Waiting items cancelled by the shop", "backorders",
              variables=(*_ORDER, "product", "quantity"), shop_facing=False),
        Event("stock.alert_opened", "Stock low, out, or wanted by waiting orders", "stock",
              urgent=False, variables=("distributor", "product", "alert", "quantity", "link"),
              shop_facing=False),
        Event("invoice.issued", "Tax invoice issued", "billing",
              variables=("distributor", "shop", "invoice_number", "total", "due_date",
                         "order_number", "document_link", "link"),
              document=DocumentLink.Kind.INVOICE),
        Event("credit_note.issued", "Credit note issued", "billing",
              variables=("distributor", "shop", "credit_note_number", "total", "invoice_number",
                         "reason", "document_link", "link"),
              document=DocumentLink.Kind.CREDIT_NOTE),
        Event("invoice.cancelled", "Invoice cancelled (its IRN was cancelled)", "billing",
              variables=("distributor", "shop", "invoice_number", "note", "link"),
              staff_facing=False, feature="einvoice"),
        Event("ewaybill.failed", "E-way bill failed for a shipment", "billing",
              variables=("distributor", "shop", "shipment", "vehicle", "invoice_number", "error",
                         "link"),
              shop_facing=False, feature="ewaybill"),
        Event("purchase_order.sent", "Purchase order sent to the supplier", "purchasing",
              variables=("distributor", "supplier", "po_number", "revision", "expected_date",
                         "document_link"),
              document=DocumentLink.Kind.PURCHASE_ORDER, shop_facing=False, staff_facing=False,
              supplier_facing=True, feature="purchasing"),
        Event("purchase_order.cancelled", "Purchase order cancelled (to the supplier)",
              "purchasing", variables=("distributor", "supplier", "po_number", "reason",
                                       "document_link"),
              document=DocumentLink.Kind.PURCHASE_ORDER, shop_facing=False, staff_facing=False,
              supplier_facing=True, feature="purchasing"),
        Event("report.ready", "Report ready to download", "other",
              variables=("report", "rows", "days", "link"), shop_facing=False, system=True),
        Event("report.failed", "Report could not be made", "other",
              variables=("report", "error", "link"), shop_facing=False, system=True),
        Event("einvoice.failed", "IRN failed for an invoice or credit note", "billing",
              variables=("distributor", "shop", "document_number", "error", "link"),
              shop_facing=False, feature="einvoice"),
        Event("payment.received", "Payment received", "payments",
              variables=("distributor", "shop", "receipt_number", "amount", "mode",
                         "document_link", "link"),
              document=DocumentLink.Kind.RECEIPT),
        Event("payment.cleared", "Cheque cleared", "payments",
              variables=("distributor", "shop", "receipt_number", "amount", "cheque_number",
                         "link")),
        Event("payment.bounced", "Cheque bounced", "payments",
              variables=("distributor", "shop", "receipt_number", "amount", "cheque_number",
                         "cheque_date", "reason", "balance", "document_link", "link"),
              document=DocumentLink.Kind.RECEIPT),
        Event("payment.reversed", "Payment reversed (entered in error)", "payments",
              variables=("distributor", "shop", "receipt_number", "amount", "reason", "link")),
        Event("payment.handed_over", "Collection handed over", "payments",
              variables=("distributor", "shop", "receipt_number", "amount", "link"),
              shop_facing=False),
        Event("refund.recorded", "Refund paid to the shop", "payments",
              variables=("distributor", "shop", "refund_number", "amount", "mode",
                         "document_link", "link"),
              document=DocumentLink.Kind.REFUND_VOUCHER),
        Event("refund.reversed", "Refund reversed", "payments",
              variables=("distributor", "shop", "refund_number", "amount", "reason", "link")),
        Event("payment.reminder", "Payment reminder (bills due soon or overdue)", "reminders",
              urgent=False,
              variables=("distributor", "shop", "bills", "amount", "overdue", "due_note",
                         "link")),
        Event("handover.reminder", "Collections not yet handed over", "reminders", urgent=False,
              variables=("distributor", "salesman", "count", "amount", "oldest", "link"),
              shop_facing=False),
        # ADR-056: one per person per morning, with only what their permissions show.
        Event("summary.daily", "Daily summary", "reminders", urgent=False,
              variables=("distributor", "date", "yesterday", "attention", "yesterday_lines",
                         "attention_lines", "link"),
              shop_facing=False),
        Event("tax.rate_change_upcoming", "GST rate changes in 7 days", "other", urgent=False,
              variables=("distributor", "count", "change_date", "products", "link"),
              shop_facing=False),
        Event("retailer.welcome", "Welcome message to a new shop", "other",
              variables=("distributor", "shop", "link"), staff_facing=False),
        Event("announcement.published", "Announcement", "other", urgent=False,
              category=MARKETING, variables=("distributor", "shop", "title", "message", "link"),
              staff_facing=False),
    )
}  # fmt: skip


@dataclass(frozen=True)
class Rule:
    event: str
    recipient: str
    channels: tuple[str, ...]
    permission: str = ""
    compulsory: bool = False

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.event, self.recipient, self.permission)


S, SP, CO, ST = (
    Recipient.SHOP,
    Recipient.SALESPERSON,
    Recipient.COLLECTOR,
    Recipient.STAFF_PERMISSION,
)
DEFAULT_RULES: tuple[Rule, ...] = (
    Rule("order.placed", ST, (IN,), "orders.manage"),
    Rule("order.placed", SP, (IN,)),
    Rule("order.placed", S, (IN,)),
    Rule("order.placed_for_shop", ST, (IN,), "orders.manage"),
    Rule("order.placed_for_shop", SP, (IN,)),
    Rule("order.placed_for_shop", S, (IN, WA)),
    Rule("order.on_hold", ST, (IN, EM), "credit.manage"),
    Rule("order.on_hold", S, (IN,)),
    Rule("order.hold_approved", S, (IN,)),
    Rule("order.accepted", S, (IN, WA)),
    Rule("order.rejected", S, (IN, WA)),
    Rule("order.cancelled", S, (IN, WA)),
    Rule("order.cancelled_by_shop", ST, (IN,), "orders.manage"),
    Rule("order.modified", S, (IN, WA)),
    Rule("order.short_supplied", S, (IN, WA)),
    Rule("order.dispatched", S, (IN,)),
    Rule("order.dispatched_after_invoice", S, (IN, WA)),
    Rule("order.delivered", S, (IN,)),
    Rule("order.completed", S, (IN,)),
    Rule("backorder.proposed", ST, (IN,), "orders.allocate_backorder"),
    Rule("backorder.allocated", S, (IN, WA)),
    Rule("backorder.skipped_credit", ST, (IN,), "credit.manage"),
    Rule("backorder.skipped_blocked", ST, (IN,), "credit.manage"),
    Rule("backorder.cancelled", S, (IN,)),
    Rule("backorder.cancelled_by_shop", ST, (IN,), "orders.manage"),
    Rule("stock.alert_opened", ST, (IN,), "stock.inward"),
    Rule("invoice.issued", S, (IN, WA, EM), compulsory=True),
    Rule("credit_note.issued", S, (IN, WA, EM), compulsory=True),
    Rule("invoice.cancelled", S, (IN, EM)),  # Phase 7 backend checkpoint, change 3
    Rule("einvoice.failed", ST, (IN, EM), "compliance.manage"),
    # Phase 7 backend checkpoint, change 4: at once, whatever the hour (urgent).
    Rule("ewaybill.failed", ST, (IN, EM), "compliance.manage"),
    Rule("ewaybill.failed", Recipient.DISPATCHER, (IN, EM)),
    Rule("purchase_order.sent", Recipient.SUPPLIER, (EM,)),  # ADR-053: email only
    Rule("purchase_order.cancelled", Recipient.SUPPLIER, (EM,)),
    Rule("report.ready", Recipient.REQUESTER, (IN,)),  # ADR-050: in-app only
    Rule("report.failed", Recipient.REQUESTER, (IN,)),
    Rule("payment.received", S, (IN, WA, EM)),
    Rule("payment.cleared", S, (IN,)),
    Rule("payment.bounced", S, (IN, WA), compulsory=True),
    Rule("payment.bounced", ST, (IN,), "payments.record"),
    Rule("payment.bounced", SP, (IN,)),
    Rule("payment.reversed", S, (IN,)),
    Rule("payment.handed_over", CO, (IN,)),
    Rule("refund.recorded", S, (IN, WA)),
    Rule("refund.reversed", S, (IN,)),
    Rule("payment.reminder", S, (IN, WA), compulsory=True),
    Rule("payment.reminder", SP, (IN,)),
    Rule("handover.reminder", CO, (IN, WA)),
    Rule("handover.reminder", ST, (IN,), "payments.record"),
    Rule("summary.daily", Recipient.OWNERS, (IN, EM)),  # ADR-056
    Rule("tax.rate_change_upcoming", ST, (IN, EM), "products.manage"),
    Rule("retailer.welcome", S, (SMS,), compulsory=True),
    Rule("announcement.published", S, (IN,)),
)

# Which channels each recipient can use (the rules screen offers only these).
RECIPIENT_CHANNELS: dict[str, tuple[str, ...]] = {
    S: (IN, WA, EM, SMS),
    SP: (IN, WA, EM),
    CO: (IN, WA, EM),
    ST: (IN, WA, EM),
    Recipient.OWNERS: (IN, WA, EM),
    Recipient.DISPATCHER: (IN, WA, EM),
    Recipient.REQUESTER: (IN,),
    Recipient.SUPPLIER: (EM,),
}
# Recipients of system messages only: never offered on the rules screen.
SYSTEM_RECIPIENTS = frozenset({Recipient.REQUESTER})
# Recipients that exist only for some events (and only while their module is on).
ONLY_FOR: dict[str, tuple[tuple[str, ...], str]] = {
    Recipient.DISPATCHER: (("ewaybill.failed",), "ewaybill"),
    Recipient.SUPPLIER: (("purchase_order.sent", "purchase_order.cancelled"), "purchasing"),
}


@dataclass(frozen=True)
class Text:
    subject: str  # in-app title / email subject
    body: str
    variables: tuple[str, ...] = field(default=())  # WhatsApp parameters, in order


_VAR = re.compile(r"{{\s*(\w+)\s*}}")


def _wa(body: str) -> Text:
    """A WhatsApp text: its parameters are its variables in order of first use."""
    return Text("", body, tuple(dict.fromkeys(_VAR.findall(body))))


def _pair(subject: str, body: str, whatsapp: str, *, email_subject: str = "") -> dict[str, Text]:
    """In-app and email say the same (email adds the page's link); WhatsApp is short."""
    return {
        IN: Text(subject, body),
        EM: Text(email_subject or subject, f"{body}\n\n{{{{ link }}}}"),
        WA: _wa(whatsapp),
    }


D = "{{ distributor }}"
# The shop's words: "Your order …". Every event a shop can get has them.
SHOP_TEXTS: dict[str, dict[str, Text]] = {
    "order.placed_for_shop": {
        IN: Text("Order {{ order_number }} placed for you", "{{ placed_by }} placed order {{ order_number }} for {{ total }} on your behalf."),
        EM: Text("Order {{ order_number }} placed for you", "{{ placed_by }} at {{ distributor }} placed order {{ order_number }} for {{ total }} for you.\n\nSee it: {{ link }}"),
        WA: Text("", f"{D}: {{{{ placed_by }}}} placed order {{{{ order_number }}}} for {{{{ total }}}} for you. See it: {{{{ link }}}}", ("distributor", "placed_by", "order_number", "total", "link")),
    },
    "order.hold_approved": {
        IN: Text("Order {{ order_number }} approved", "Your order {{ order_number }} was approved and will be processed."),
        EM: Text("Order {{ order_number }} approved", "Your order {{ order_number }} with {{ distributor }} was approved.\n\n{{ link }}"),
        WA: Text("", f"{D}: your order {{{{ order_number }}}} was approved.", ("distributor", "order_number")),
    },
    "order.accepted": {
        IN: Text("Order {{ order_number }} accepted", "Your order {{ order_number }} for {{ total }} was accepted."),
        EM: Text("Order {{ order_number }} accepted", "{{ distributor }} accepted your order {{ order_number }} for {{ total }}.\n\nOrder Confirmation: {{ document_link }}"),
        WA: Text("", f"{D}: your order {{{{ order_number }}}} for {{{{ total }}}} was accepted. Order Confirmation: {{{{ document_link }}}}", ("distributor", "order_number", "total", "document_link")),
    },
    "order.rejected": {
        IN: Text("Order {{ order_number }} not accepted", "Your order {{ order_number }} was not accepted: {{ reason }}."),
        EM: Text("Order {{ order_number }} not accepted", "{{ distributor }} could not accept your order {{ order_number }}: {{ reason }}."),
        WA: Text("", f"{D}: your order {{{{ order_number }}}} was not accepted: {{{{ reason }}}}.", ("distributor", "order_number", "reason")),
    },
    "order.cancelled": {
        IN: Text("Order {{ order_number }} cancelled", "Your order {{ order_number }} was cancelled: {{ reason }}."),
        EM: Text("Order {{ order_number }} cancelled", "{{ distributor }} cancelled your order {{ order_number }}: {{ reason }}."),
        WA: Text("", f"{D}: your order {{{{ order_number }}}} was cancelled: {{{{ reason }}}}.", ("distributor", "order_number", "reason")),
    },
    "order.modified": {
        IN: Text("Order {{ order_number }} changed", "Your order {{ order_number }} was changed: {{ changes }}. New total {{ total }}."),
        EM: Text("Order {{ order_number }} changed", "{{ distributor }} changed your order {{ order_number }}: {{ changes }}. New total {{ total }}.\n\n{{ link }}"),
        WA: Text("", f"{D}: your order {{{{ order_number }}}} was changed: {{{{ changes }}}}. New total {{{{ total }}}}.", ("distributor", "order_number", "changes", "total")),
    },
    "order.short_supplied": {
        IN: Text("Less supplied on {{ order_number }}", "Less than ordered was packed on {{ order_number }}: {{ items }}."),
        EM: Text("Less supplied on {{ order_number }}", "{{ distributor }} packed less than ordered on {{ order_number }}: {{ items }}.\n\n{{ link }}"),
        WA: Text("", f"{D}: less than ordered was packed on {{{{ order_number }}}}: {{{{ items }}}}.", ("distributor", "order_number", "items")),
    },
    "order.dispatched": {
        IN: Text("Order {{ order_number }} is on its way", "Shipment {{ shipment }} of order {{ order_number }} left the warehouse{{ vehicle }}."),
        EM: Text("Order {{ order_number }} is on its way", "{{ distributor }} dispatched shipment {{ shipment }} of order {{ order_number }}{{ vehicle }}.\n\n{{ link }}"),
        WA: Text("", f"{D}: your order {{{{ order_number }}}} is on its way (shipment {{{{ shipment }}}}).", ("distributor", "order_number", "shipment")),
    },
    "order.dispatched_after_invoice": {
        IN: Text("Order {{ order_number }} is on its way", "Shipment {{ shipment }} of order {{ order_number }} left the warehouse{{ vehicle }}."),
        EM: Text("Order {{ order_number }} is on its way", "{{ distributor }} dispatched shipment {{ shipment }} of order {{ order_number }}{{ vehicle }}. Transporter {{ transporter }}, LR {{ lr_number }}.\n\n{{ link }}"),
        WA: Text("", f"{D}: your order {{{{ order_number }}}} is on its way (shipment {{{{ shipment }}}}{{{{ vehicle }}}}).", ("distributor", "order_number", "shipment", "vehicle")),
    },
    "order.delivered": {
        IN: Text("Order {{ order_number }} delivered", "Shipment {{ shipment }} of order {{ order_number }} was delivered."),
        EM: Text("Order {{ order_number }} delivered", "Shipment {{ shipment }} of order {{ order_number }} was delivered.\n\n{{ link }}"),
        WA: Text("", f"{D}: shipment {{{{ shipment }}}} of order {{{{ order_number }}}} was delivered.", ("distributor", "shipment", "order_number")),
    },
    "order.completed": {
        IN: Text("Order {{ order_number }} complete", "Everything on order {{ order_number }} was delivered."),
        EM: Text("Order {{ order_number }} complete", "Everything on order {{ order_number }} was delivered.\n\n{{ link }}"),
        WA: Text("", f"{D}: everything on order {{{{ order_number }}}} was delivered.", ("distributor", "order_number")),
    },
    "backorder.allocated": {
        IN: Text("Waiting items on their way", "Items you were waiting for on {{ order_number }} are being sent (shipment {{ shipment }}).{{ price_increased }}"),
        EM: Text("Waiting items for {{ order_number }}", "{{ distributor }} is sending items you were waiting for on {{ order_number }} (shipment {{ shipment }}).{{ price_increased }}\n\n{{ link }}"),
        WA: Text("", f"{D}: items you were waiting for on {{{{ order_number }}}} are being sent.{{{{ price_increased }}}} {{{{ link }}}}", ("distributor", "order_number", "price_increased", "link")),
    },
    "backorder.cancelled": {
        IN: Text("Waiting items cancelled", "{{ quantity }} {{ product }} you were waiting for on {{ order_number }} was cancelled."),
        EM: Text("Waiting items cancelled on {{ order_number }}", "{{ distributor }} cancelled {{ quantity }} {{ product }} you were waiting for on {{ order_number }}.\n\n{{ link }}"),
        WA: Text("", f"{D}: {{{{ quantity }}}} {{{{ product }}}} you were waiting for on {{{{ order_number }}}} was cancelled.", ("distributor", "quantity", "product", "order_number")),
    },
    "invoice.issued": {
        IN: Text("Bill {{ invoice_number }}: {{ total }}", "Your bill {{ invoice_number }} for order {{ order_number }} is {{ total }}, to pay by {{ due_date }}."),
        EM: Text("Tax invoice {{ invoice_number }} from {{ distributor }}", "Your tax invoice {{ invoice_number }} for order {{ order_number }} is {{ total }}, to pay by {{ due_date }}.\n\nDownload it: {{ document_link }}"),
        WA: Text("", f"{D}: your order {{{{ order_number }}}} is on its way. Bill {{{{ invoice_number }}}}: {{{{ total }}}}, pay by {{{{ due_date }}}}. {{{{ document_link }}}}", ("distributor", "order_number", "invoice_number", "total", "due_date", "document_link")),
    },
    "invoice.cancelled": {
        IN: Text("Bill {{ invoice_number }} cancelled", "Your bill {{ invoice_number }} was cancelled. {{ note }}"),
        EM: Text("Bill {{ invoice_number }} cancelled", "Your bill {{ invoice_number }} from {{ distributor }} was cancelled. {{ note }}\n\nSee it here: {{ link }}"),
        WA: Text("", f"{D}: your bill {{{{ invoice_number }}}} was cancelled. {{{{ note }}}}", ("distributor", "invoice_number", "note")),
    },
    "credit_note.issued": {
        IN: Text("Credit note {{ credit_note_number }}: {{ total }}", "You were credited {{ total }} against bill {{ invoice_number }} ({{ reason }})."),
        EM: Text("Credit note {{ credit_note_number }} from {{ distributor }}", "You were credited {{ total }} against bill {{ invoice_number }} ({{ reason }}).\n\nDownload it: {{ document_link }}"),
        WA: Text("", f"{D}: credit note {{{{ credit_note_number }}}} for {{{{ total }}}} against bill {{{{ invoice_number }}}}. {{{{ document_link }}}}", ("distributor", "credit_note_number", "total", "invoice_number", "document_link")),
    },
    "payment.received": {
        IN: Text("Payment received: {{ amount }}", "Thank you: {{ amount }} by {{ mode }} (receipt {{ receipt_number }})."),
        EM: Text("Receipt {{ receipt_number }} from {{ distributor }}", "Thank you for your payment of {{ amount }} by {{ mode }}.\n\nReceipt: {{ document_link }}"),
        WA: Text("", f"{D}: payment of {{{{ amount }}}} received, thank you. Receipt: {{{{ document_link }}}}", ("distributor", "amount", "document_link")),
    },
    "payment.cleared": {
        IN: Text("Cheque cleared", "Your cheque {{ cheque_number }} for {{ amount }} cleared."),
        EM: Text("Cheque cleared", "Your cheque {{ cheque_number }} for {{ amount }} cleared.\n\n{{ link }}"),
        WA: Text("", f"{D}: your cheque {{{{ cheque_number }}}} for {{{{ amount }}}} cleared.", ("distributor", "cheque_number", "amount")),
    },
    "payment.bounced": {
        IN: Text("Cheque {{ cheque_number }} bounced", "Your cheque {{ cheque_number }} dated {{ cheque_date }} for {{ amount }} bounced ({{ reason }}). The bills it paid are due again. Your balance: {{ balance }}."),
        EM: Text("Cheque {{ cheque_number }} bounced", "Your cheque {{ cheque_number }} dated {{ cheque_date }} for {{ amount }} bounced ({{ reason }}). The bills it paid are due again. Your balance: {{ balance }}.\n\n{{ document_link }}"),
        WA: Text("", f"{D}: your cheque {{{{ cheque_number }}}} dated {{{{ cheque_date }}}} for {{{{ amount }}}} bounced ({{{{ reason }}}}). The bills it paid are due again. Your balance: {{{{ balance }}}}.", ("distributor", "cheque_number", "cheque_date", "amount", "reason", "balance")),
    },
    "payment.reversed": {
        IN: Text("Payment corrected", "Payment {{ receipt_number }} of {{ amount }} was reversed: {{ reason }}."),
        EM: Text("Payment corrected", "Payment {{ receipt_number }} of {{ amount }} was reversed: {{ reason }}.\n\n{{ link }}"),
        WA: Text("", f"{D}: payment {{{{ receipt_number }}}} of {{{{ amount }}}} was reversed: {{{{ reason }}}}.", ("distributor", "receipt_number", "amount", "reason")),
    },
    "refund.recorded": {
        IN: Text("Refund of {{ amount }}", "{{ distributor }} paid you back {{ amount }} by {{ mode }} (voucher {{ refund_number }})."),
        EM: Text("Refund voucher {{ refund_number }}", "{{ distributor }} paid you back {{ amount }} by {{ mode }}.\n\nVoucher: {{ document_link }}"),
        WA: Text("", f"{D}: we paid you back {{{{ amount }}}} by {{{{ mode }}}}. Voucher: {{{{ document_link }}}}", ("distributor", "amount", "mode", "document_link")),
    },
    "refund.reversed": {
        IN: Text("Refund corrected", "Refund {{ refund_number }} of {{ amount }} was reversed: {{ reason }}. It is back in your credit."),
        EM: Text("Refund corrected", "Refund {{ refund_number }} of {{ amount }} was reversed: {{ reason }}.\n\n{{ link }}"),
        WA: Text("", f"{D}: refund {{{{ refund_number }}}} of {{{{ amount }}}} was reversed: {{{{ reason }}}}.", ("distributor", "refund_number", "amount", "reason")),
    },
    "payment.reminder": {
        IN: Text("Payment reminder: {{ amount }}", "{{ bills }} to pay, {{ amount }} in all ({{ due_note }}). Please pay on time."),
        EM: Text("Payment reminder from {{ distributor }}", "You have {{ bills }} to pay, {{ amount }} in all ({{ due_note }}). Please pay on time.\n\nYour bills and statement: {{ link }}"),
        WA: Text("", f"{D}: you have {{{{ bills }}}} to pay, {{{{ amount }}}} in all ({{{{ due_note }}}}). Please pay on time. {{{{ link }}}}", ("distributor", "bills", "amount", "due_note", "link")),
    },
    "retailer.welcome": {
        SMS: Text("", f"{D}: welcome, {{{{ shop }}}}! Order from your phone: {{{{ link }}}}"),
        IN: Text("Welcome to {{ distributor }}", "Order any time from your phone. Your bills and payments are here too."),
        WA: Text("", f"{D}: welcome, {{{{ shop }}}}! Order from your phone: {{{{ link }}}}", ("distributor", "shop", "link")),
        EM: Text("Welcome to {{ distributor }}", "Welcome, {{ shop }}! Order from your phone: {{ link }}"),
    },
    "announcement.published": {
        IN: Text("{{ title }}", "{{ message }}"),
        EM: Text("{{ distributor }}: {{ title }}", "{{ message }}\n\n{{ link }}"),
        WA: Text("", f"{D}: {{{{ title }}}}. {{{{ message }}}}", ("distributor", "title", "message")),
    },
    # Events whose first texts were written for the office (both audiences by default).
    "order.placed": _pair(
        "Order {{ order_number }} placed",
        "Your order {{ order_number }} for {{ total }} has been placed. {{ distributor }} will confirm it soon.",
        "{{ distributor }}: your order {{ order_number }} for {{ total }} has been placed.",
        email_subject="Order {{ order_number }} placed with {{ distributor }}",
    ),
    "order.on_hold": _pair(
        "Order {{ order_number }} waits for approval",
        "Your order {{ order_number }} ({{ total }}) is waiting for {{ distributor }}'s approval: {{ hold_reason }}.",
        "{{ distributor }}: your order {{ order_number }} ({{ total }}) is waiting for approval: {{ hold_reason }}.",
    ),
}  # fmt: skip

# The office's words: "Ganesh Kirana's order …". Every event staff can get has them.
STAFF_TEXTS: dict[str, dict[str, Text]] = {
    "report.ready": {
        IN: Text("Report ready: {{ report }}", "{{ report }} is ready ({{ rows }} rows). Download it within {{ days }} days."),
        EM: Text("Report ready: {{ report }}", "{{ report }} is ready ({{ rows }} rows). Download it within {{ days }} days.\n\n{{ link }}"),
    },
    "report.failed": {
        IN: Text("Report not made: {{ report }}", "{{ report }} could not be made: {{ error }}"),
        EM: Text("Report not made: {{ report }}", "{{ report }} could not be made: {{ error }}\n\n{{ link }}"),
    },
    "order.placed": {
        IN: Text("New order {{ order_number }}", "{{ shop }} placed order {{ order_number }} for {{ total }}."),
        EM: Text("New order {{ order_number }} from {{ shop }}", "{{ shop }} placed order {{ order_number }} for {{ total }}.\n\nOpen it: {{ link }}"),
        WA: Text("", f"{D}: new order {{{{ order_number }}}} from {{{{ shop }}}} for {{{{ total }}}}.", ("distributor", "order_number", "shop", "total")),
    },
    "order.on_hold": {
        IN: Text("Order {{ order_number }} waits for approval", "{{ shop }}'s order {{ order_number }} ({{ total }}) is on hold: {{ hold_reason }}."),
        EM: Text("Order {{ order_number }} needs credit approval", "{{ shop }}'s order {{ order_number }} for {{ total }} is on hold: {{ hold_reason }}.\n\nReview it: {{ link }}"),
        WA: Text("", f"{D}: order {{{{ order_number }}}} is waiting for approval ({{{{ hold_reason }}}}).", ("distributor", "order_number", "hold_reason")),
    },
    "order.cancelled_by_shop": {
        IN: Text("{{ shop }} cancelled {{ order_number }}", "{{ shop }} cancelled order {{ order_number }} ({{ total }})."),
        EM: Text("{{ shop }} cancelled {{ order_number }}", "{{ shop }} cancelled order {{ order_number }} ({{ total }}).\n\n{{ link }}"),
        WA: Text("", f"{D}: {{{{ shop }}}} cancelled order {{{{ order_number }}}}.", ("distributor", "shop", "order_number")),
    },
    "backorder.proposed": {
        IN: Text("Stock ready for {{ order_number }}", "{{ quantity }} {{ product }} can go to {{ shop }} ({{ order_number }}). Confirm it."),
        EM: Text("Stock ready for {{ order_number }}", "{{ quantity }} {{ product }} can go to {{ shop }} ({{ order_number }}).\n\nConfirm: {{ link }}"),
        WA: Text("", f"{D}: {{{{ quantity }}}} {{{{ product }}}} is ready for {{{{ shop }}}} ({{{{ order_number }}}}).", ("distributor", "quantity", "product", "shop", "order_number")),
    },
    "backorder.skipped_credit": {
        IN: Text("Waiting items held for {{ shop }}", "{{ quantity }} {{ product }} for {{ order_number }} was not allocated: {{ shop }} is over its credit."),
        EM: Text("Waiting items held for {{ shop }}", "{{ quantity }} {{ product }} for {{ order_number }} was not allocated: {{ shop }} is over its credit.\n\n{{ link }}"),
        WA: Text("", f"{D}: {{{{ product }}}} for {{{{ order_number }}}} held: {{{{ shop }}}} is over its credit.", ("distributor", "product", "order_number", "shop")),
    },
    "backorder.skipped_blocked": {
        IN: Text("Waiting items held for {{ shop }}", "{{ quantity }} {{ product }} for {{ order_number }} was not allocated: {{ shop }} is blocked."),
        EM: Text("Waiting items held for {{ shop }}", "{{ quantity }} {{ product }} for {{ order_number }} was not allocated: {{ shop }} is blocked.\n\n{{ link }}"),
        WA: Text("", f"{D}: {{{{ product }}}} for {{{{ order_number }}}} held: {{{{ shop }}}} is blocked.", ("distributor", "product", "order_number", "shop")),
    },
    "backorder.cancelled_by_shop": {
        IN: Text("{{ shop }} cancelled waiting items", "{{ shop }} cancelled {{ quantity }} {{ product }} on {{ order_number }}."),
        EM: Text("{{ shop }} cancelled waiting items", "{{ shop }} cancelled {{ quantity }} {{ product }} on {{ order_number }}.\n\n{{ link }}"),
        WA: Text("", f"{D}: {{{{ shop }}}} cancelled {{{{ product }}}} on {{{{ order_number }}}}.", ("distributor", "shop", "product", "order_number")),
    },
    "stock.alert_opened": {
        IN: Text("{{ product }}: {{ alert }}", "{{ product }} is {{ alert }} ({{ quantity }} left)."),
        EM: Text("{{ product }}: {{ alert }}", "{{ product }} is {{ alert }} ({{ quantity }} left).\n\n{{ link }}"),
        WA: Text("", f"{D}: {{{{ product }}}} is {{{{ alert }}}} ({{{{ quantity }}}} left).", ("distributor", "product", "alert", "quantity")),
    },
    "ewaybill.failed": {
        IN: Text("E-way bill failed: {{ shipment }}", "No e-way bill for shipment {{ shipment }} ({{ shop }}, vehicle {{ vehicle }}, bill {{ invoice_number }}): {{ error }}"),
        EM: Text("E-way bill failed: {{ shipment }}", "No e-way bill for shipment {{ shipment }} ({{ shop }}, vehicle {{ vehicle }}, bill {{ invoice_number }}): {{ error }}\n\nFix it and try again: {{ link }}"),
        WA: Text("", f"{D}: e-way bill failed for {{{{ shipment }}}} ({{{{ shop }}}}, vehicle {{{{ vehicle }}}}): {{{{ error }}}}", ("distributor", "shipment", "shop", "vehicle", "error")),
    },
    "einvoice.failed": {
        IN: Text("IRN failed: {{ document_number }}", "The e-invoice portal did not give an IRN for {{ document_number }} ({{ shop }}): {{ error }}"),
        EM: Text("IRN failed: {{ document_number }}", "The e-invoice portal did not give an IRN for {{ document_number }} ({{ shop }}): {{ error }}\n\nFix it and try again: {{ link }}"),
        WA: Text("", f"{D}: IRN failed for {{{{ document_number }}}} ({{{{ shop }}}}): {{{{ error }}}}", ("distributor", "document_number", "shop", "error")),
    },
    "payment.handed_over": {
        IN: Text("Collection handed over", "{{ receipt_number }} ({{ amount }} from {{ shop }}) was marked handed over."),
        EM: Text("Collection handed over", "{{ receipt_number }} ({{ amount }} from {{ shop }}) was marked handed over.\n\n{{ link }}"),
        WA: Text("", f"{D}: {{{{ receipt_number }}}} ({{{{ amount }}}} from {{{{ shop }}}}) was marked handed over.", ("distributor", "receipt_number", "amount", "shop")),
    },
    "handover.reminder": {
        IN: Text("{{ amount }} not handed over", "{{ salesman }} has {{ count }} collections ({{ amount }}) not handed over; the oldest is from {{ oldest }}."),
        EM: Text("Collections not handed over", "{{ salesman }} has {{ count }} collections ({{ amount }}) not handed over; the oldest is from {{ oldest }}.\n\n{{ link }}"),
        WA: Text("", f"{D}: {{{{ count }}}} collections ({{{{ amount }}}}) are not handed over yet; the oldest is from {{{{ oldest }}}}.", ("distributor", "count", "amount", "oldest")),
    },
    "summary.daily": {
        IN: Text("Your summary for {{ date }}", "Yesterday: {{ yesterday }}. Needs action: {{ attention }}."),
        EM: Text("{{ distributor }}: summary for {{ date }}", "Yesterday, {{ date }}:\n{{ yesterday_lines }}\n\nNeeds action now:\n{{ attention_lines }}\n\n{{ link }}"),
        WA: Text("", f"{D}: yesterday {{{{ yesterday }}}}. Needs action: {{{{ attention }}}}.", ("distributor", "yesterday", "attention")),
    },
    "tax.rate_change_upcoming": {
        IN: Text("GST changes on {{ change_date }}", "The GST rate of {{ count }} products changes on {{ change_date }}: {{ products }}."),
        EM: Text("GST changes on {{ change_date }}", "The GST rate of {{ count }} products changes on {{ change_date }}: {{ products }}.\n\n{{ link }}"),
        WA: Text("", f"{D}: the GST rate of {{{{ count }}}} products changes on {{{{ change_date }}}}.", ("distributor", "count", "change_date")),
    },
    # The office's view of events first written for the shop.
    "order.placed_for_shop": _pair(
        "Order {{ order_number }} placed for {{ shop }}",
        "{{ placed_by }} placed order {{ order_number }} for {{ shop }} ({{ total }}).",
        "{{ distributor }}: {{ placed_by }} placed order {{ order_number }} for {{ shop }} ({{ total }}).",
    ),
    "order.hold_approved": _pair(
        "Order {{ order_number }} approved",
        "{{ shop }}'s order {{ order_number }} ({{ total }}) was approved and will be processed.",
        "{{ distributor }}: {{ shop }}'s order {{ order_number }} was approved.",
    ),
    "order.accepted": _pair(
        "Order {{ order_number }} accepted",
        "{{ shop }}'s order {{ order_number }} ({{ total }}) was accepted.",
        "{{ distributor }}: {{ shop }}'s order {{ order_number }} ({{ total }}) was accepted.",
    ),
    "order.rejected": _pair(
        "Order {{ order_number }} rejected",
        "{{ shop }}'s order {{ order_number }} was rejected: {{ reason }}.",
        "{{ distributor }}: {{ shop }}'s order {{ order_number }} was rejected: {{ reason }}.",
    ),
    "order.cancelled": _pair(
        "Order {{ order_number }} cancelled",
        "{{ shop }}'s order {{ order_number }} ({{ total }}) was cancelled: {{ reason }}.",
        "{{ distributor }}: {{ shop }}'s order {{ order_number }} was cancelled: {{ reason }}.",
    ),
    "order.modified": _pair(
        "Order {{ order_number }} changed",
        "{{ shop }}'s order {{ order_number }} was changed: {{ changes }}. New total {{ total }}.",
        "{{ distributor }}: {{ shop }}'s order {{ order_number }} was changed: {{ changes }}.",
    ),
    "order.short_supplied": _pair(
        "Short supply on {{ order_number }}",
        "{{ shop }}'s order {{ order_number }} was packed short: {{ items }}.",
        "{{ distributor }}: {{ shop }}'s order {{ order_number }} was packed short: {{ items }}.",
    ),
    "order.dispatched": _pair(
        "Order {{ order_number }} dispatched",
        "Shipment {{ shipment }} of {{ shop }}'s order {{ order_number }} left the warehouse{{ vehicle }}.",
        "{{ distributor }}: shipment {{ shipment }} of {{ shop }}'s order {{ order_number }} was dispatched.",
    ),
    "order.dispatched_after_invoice": _pair(
        "Order {{ order_number }} dispatched",
        "Shipment {{ shipment }} of {{ shop }}'s order {{ order_number }} left the warehouse{{ vehicle }}.",
        "{{ distributor }}: shipment {{ shipment }} of {{ shop }}'s order {{ order_number }} was dispatched.",
    ),
    "order.delivered": _pair(
        "Order {{ order_number }} delivered",
        "Shipment {{ shipment }} of {{ shop }}'s order {{ order_number }} was delivered.",
        "{{ distributor }}: shipment {{ shipment }} of {{ shop }}'s order {{ order_number }} was delivered.",
    ),
    "order.completed": _pair(
        "Order {{ order_number }} complete",
        "Everything on {{ shop }}'s order {{ order_number }} was delivered.",
        "{{ distributor }}: everything on {{ shop }}'s order {{ order_number }} was delivered.",
    ),
    "backorder.allocated": _pair(
        "Waiting items going to {{ shop }}",
        "Items {{ shop }} was waiting for on {{ order_number }} are being sent (shipment {{ shipment }}).{{ price_increased }}",
        "{{ distributor }}: items {{ shop }} was waiting for on {{ order_number }} are being sent (shipment {{ shipment }}).",
    ),
    "backorder.cancelled": _pair(
        "Waiting items cancelled for {{ shop }}",
        "{{ quantity }} {{ product }} that {{ shop }} was waiting for on {{ order_number }} was cancelled.",
        "{{ distributor }}: {{ quantity }} {{ product }} for {{ shop }} on {{ order_number }} was cancelled.",
    ),
    "invoice.issued": _pair(
        "Bill {{ invoice_number }} for {{ shop }}",
        "Bill {{ invoice_number }} for {{ shop }}'s order {{ order_number }}: {{ total }}, due {{ due_date }}.",
        "{{ distributor }}: bill {{ invoice_number }} for {{ shop }}: {{ total }}, due {{ due_date }}.",
    ),
    "credit_note.issued": _pair(
        "Credit note {{ credit_note_number }} for {{ shop }}",
        "{{ shop }} was credited {{ total }} against bill {{ invoice_number }} ({{ reason }}).",
        "{{ distributor }}: credit note {{ credit_note_number }} for {{ shop }}: {{ total }} against bill {{ invoice_number }}.",
    ),
    "payment.received": _pair(
        "{{ amount }} received from {{ shop }}",
        "{{ shop }} paid {{ amount }} by {{ mode }} (receipt {{ receipt_number }}).",
        "{{ distributor }}: {{ shop }} paid {{ amount }} by {{ mode }} (receipt {{ receipt_number }}).",
    ),
    "payment.cleared": _pair(
        "Cheque cleared for {{ shop }}",
        "{{ shop }}'s cheque {{ cheque_number }} for {{ amount }} cleared.",
        "{{ distributor }}: {{ shop }}'s cheque {{ cheque_number }} for {{ amount }} cleared.",
    ),
    "payment.bounced": _pair(
        "{{ shop }}'s cheque {{ cheque_number }} bounced",
        "{{ shop }}'s cheque {{ cheque_number }} dated {{ cheque_date }} for {{ amount }} bounced ({{ reason }}). The bills it paid are due again; balance {{ balance }}.",
        "{{ distributor }}: {{ shop }}'s cheque {{ cheque_number }} for {{ amount }} bounced ({{ reason }}). Balance {{ balance }}.",
    ),
    "payment.reversed": _pair(
        "Payment {{ receipt_number }} reversed",
        "{{ shop }}'s payment {{ receipt_number }} of {{ amount }} was reversed: {{ reason }}.",
        "{{ distributor }}: {{ shop }}'s payment {{ receipt_number }} of {{ amount }} was reversed: {{ reason }}.",
    ),
    "refund.recorded": _pair(
        "Refund of {{ amount }} to {{ shop }}",
        "{{ shop }} was paid back {{ amount }} by {{ mode }} (voucher {{ refund_number }}).",
        "{{ distributor }}: {{ shop }} was paid back {{ amount }} by {{ mode }} (voucher {{ refund_number }}).",
    ),
    "refund.reversed": _pair(
        "Refund {{ refund_number }} reversed",
        "Refund {{ refund_number }} of {{ amount }} to {{ shop }} was reversed: {{ reason }}.",
        "{{ distributor }}: refund {{ refund_number }} of {{ amount }} to {{ shop }} was reversed: {{ reason }}.",
    ),
    "payment.reminder": _pair(
        "Reminder to {{ shop }}: {{ amount }}",
        "{{ shop }} was reminded: {{ bills }} to pay, {{ amount }} in all ({{ due_note }}).",
        "{{ distributor }}: {{ shop }} was reminded to pay {{ amount }} ({{ due_note }}).",
    ),
}  # fmt: skip

# The distributor writing to a supplier (email only, ADR-053).
SUPPLIER_TEXTS: dict[str, dict[str, Text]] = {
    "purchase_order.sent": {
        EM: Text("Purchase order {{ po_number }}{{ revision }} from {{ distributor }}", "Dear {{ supplier }},\n\nPlease find our purchase order {{ po_number }}{{ revision }}. We expect delivery by {{ expected_date }}.\n\nPurchase order: {{ document_link }}\n\nRegards,\n{{ distributor }}"),
    },
    "purchase_order.cancelled": {
        EM: Text("Purchase order {{ po_number }} cancelled by {{ distributor }}", "Dear {{ supplier }},\n\nPlease cancel our purchase order {{ po_number }}: {{ reason }}. Nothing more should be sent against it.\n\nThe cancelled order: {{ document_link }}\n\nRegards,\n{{ distributor }}"),
    },
}  # fmt: skip

# event -> audience -> channel -> text. A shop login gets the shop's words, staff the office's,
# a supplier the distributor's letter.
DEFAULT_TEXTS: dict[str, dict[str, dict[str, Text]]] = {
    code: {
        audience: texts[code]
        for audience, texts in (
            (Audience.SHOP, SHOP_TEXTS),
            (Audience.STAFF, STAFF_TEXTS),
            (Audience.SUPPLIER, SUPPLIER_TEXTS),
        )
        if code in texts
    }
    for code in EVENTS
}


def in_first_submission(event_code: str, audience: str) -> bool:
    """Whether a WhatsApp template goes in the first batch submitted to the provider for
    approval: every shop template, and the salesman's handover reminder (the only staff WhatsApp
    in the default rules). Staff otherwise rely on in-app and email; their other WhatsApp
    templates are optional and not submitted by default (Phase 6 final review). Templates of an
    optional module's events (e.g. "bill cancelled", Phase 7) are optional too."""
    if event_code == "handover.reminder":
        return True
    return audience == Audience.SHOP and not EVENTS[event_code].feature


def whatsapp_template_name(event_code: str, audience: str = Audience.SHOP) -> str:
    """The name the provider approves for this event's template (platform number); the office's
    version ends in "_staff"."""
    name = "b2b_" + event_code.replace(".", "_")
    return f"{name}_staff" if audience == Audience.STAFF else name
