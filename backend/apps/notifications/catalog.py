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

from dataclasses import dataclass, field

from apps.notifications.models import Channel, DocumentLink, Recipient, WhatsAppCategory

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
        Event("payment.received", "Payment received", "payments",
              variables=("distributor", "shop", "receipt_number", "amount", "mode",
                         "document_link", "link"),
              document=DocumentLink.Kind.RECEIPT),
        Event("payment.cleared", "Cheque cleared", "payments",
              variables=("distributor", "shop", "receipt_number", "amount", "cheque_number",
                         "link")),
        Event("payment.bounced", "Cheque bounced", "payments",
              variables=("distributor", "shop", "receipt_number", "amount", "cheque_number",
                         "reason", "document_link", "link"),
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
        Event("tax.rate_change_upcoming", "GST rate changes in 7 days", "other", urgent=False,
              variables=("distributor", "count", "change_date", "products", "link"),
              shop_facing=False),
        Event("retailer.welcome", "Welcome message to a new shop", "other",
              variables=("distributor", "shop", "link")),
        Event("announcement.published", "Announcement", "other", urgent=False,
              category=MARKETING, variables=("distributor", "shop", "title", "message", "link")),
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
}


@dataclass(frozen=True)
class Text:
    subject: str  # in-app title / email subject
    body: str
    variables: tuple[str, ...] = field(default=())  # WhatsApp parameters, in order


D = "{{ distributor }}"
# In-app and email: the same words; WhatsApp and SMS: short, naming the distributor first.
DEFAULT_TEXTS: dict[str, dict[str, Text]] = {
    "order.placed": {
        IN: Text("New order {{ order_number }}", "{{ shop }} placed order {{ order_number }} for {{ total }}."),
        EM: Text("New order {{ order_number }} from {{ shop }}", "{{ shop }} placed order {{ order_number }} for {{ total }}.\n\nOpen it: {{ link }}"),
        WA: Text("", f"{D}: new order {{{{ order_number }}}} from {{{{ shop }}}} for {{{{ total }}}}.", ("distributor", "order_number", "shop", "total")),
    },
    "order.placed_for_shop": {
        IN: Text("Order {{ order_number }} placed for you", "{{ placed_by }} placed order {{ order_number }} for {{ total }} on your behalf."),
        EM: Text("Order {{ order_number }} placed for you", "{{ placed_by }} at {{ distributor }} placed order {{ order_number }} for {{ total }} for you.\n\nSee it: {{ link }}"),
        WA: Text("", f"{D}: {{{{ placed_by }}}} placed order {{{{ order_number }}}} for {{{{ total }}}} for you. See it: {{{{ link }}}}", ("distributor", "placed_by", "order_number", "total", "link")),
    },
    "order.on_hold": {
        IN: Text("Order {{ order_number }} waits for approval", "{{ shop }}'s order {{ order_number }} ({{ total }}) is on hold: {{ hold_reason }}."),
        EM: Text("Order {{ order_number }} needs credit approval", "{{ shop }}'s order {{ order_number }} for {{ total }} is on hold: {{ hold_reason }}.\n\nReview it: {{ link }}"),
        WA: Text("", f"{D}: order {{{{ order_number }}}} is waiting for approval ({{{{ hold_reason }}}}).", ("distributor", "order_number", "hold_reason")),
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
    "order.cancelled_by_shop": {
        IN: Text("{{ shop }} cancelled {{ order_number }}", "{{ shop }} cancelled order {{ order_number }} ({{ total }})."),
        EM: Text("{{ shop }} cancelled {{ order_number }}", "{{ shop }} cancelled order {{ order_number }} ({{ total }}).\n\n{{ link }}"),
        WA: Text("", f"{D}: {{{{ shop }}}} cancelled order {{{{ order_number }}}}.", ("distributor", "shop", "order_number")),
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
    "backorder.proposed": {
        IN: Text("Stock ready for {{ order_number }}", "{{ quantity }} {{ product }} can go to {{ shop }} ({{ order_number }}). Confirm it."),
        EM: Text("Stock ready for {{ order_number }}", "{{ quantity }} {{ product }} can go to {{ shop }} ({{ order_number }}).\n\nConfirm: {{ link }}"),
        WA: Text("", f"{D}: {{{{ quantity }}}} {{{{ product }}}} is ready for {{{{ shop }}}} ({{{{ order_number }}}}).", ("distributor", "quantity", "product", "shop", "order_number")),
    },
    "backorder.allocated": {
        IN: Text("Waiting items on their way", "Items you were waiting for on {{ order_number }} are being sent (shipment {{ shipment }}).{{ price_increased }}"),
        EM: Text("Waiting items for {{ order_number }}", "{{ distributor }} is sending items you were waiting for on {{ order_number }} (shipment {{ shipment }}).{{ price_increased }}\n\n{{ link }}"),
        WA: Text("", f"{D}: items you were waiting for on {{{{ order_number }}}} are being sent.{{{{ price_increased }}}} {{{{ link }}}}", ("distributor", "order_number", "price_increased", "link")),
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
    "backorder.cancelled": {
        IN: Text("Waiting items cancelled", "{{ quantity }} {{ product }} you were waiting for on {{ order_number }} was cancelled."),
        EM: Text("Waiting items cancelled on {{ order_number }}", "{{ distributor }} cancelled {{ quantity }} {{ product }} you were waiting for on {{ order_number }}.\n\n{{ link }}"),
        WA: Text("", f"{D}: {{{{ quantity }}}} {{{{ product }}}} you were waiting for on {{{{ order_number }}}} was cancelled.", ("distributor", "quantity", "product", "order_number")),
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
    "invoice.issued": {
        IN: Text("Bill {{ invoice_number }}: {{ total }}", "Your bill {{ invoice_number }} for order {{ order_number }} is {{ total }}, to pay by {{ due_date }}."),
        EM: Text("Tax invoice {{ invoice_number }} from {{ distributor }}", "Your tax invoice {{ invoice_number }} for order {{ order_number }} is {{ total }}, to pay by {{ due_date }}.\n\nDownload it: {{ document_link }}"),
        WA: Text("", f"{D}: your order {{{{ order_number }}}} is on its way. Bill {{{{ invoice_number }}}}: {{{{ total }}}}, pay by {{{{ due_date }}}}. {{{{ document_link }}}}", ("distributor", "order_number", "invoice_number", "total", "due_date", "document_link")),
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
        IN: Text("Cheque {{ cheque_number }} bounced", "Your cheque {{ cheque_number }} for {{ amount }} bounced ({{ reason }}). The bills it paid are due again."),
        EM: Text("Cheque {{ cheque_number }} bounced", "Your cheque {{ cheque_number }} for {{ amount }} bounced ({{ reason }}). The bills it paid are due again.\n\n{{ document_link }}"),
        WA: Text("", f"{D}: your cheque {{{{ cheque_number }}}} for {{{{ amount }}}} bounced ({{{{ reason }}}}). The bills it paid are due again.", ("distributor", "cheque_number", "amount", "reason")),
    },
    "payment.reversed": {
        IN: Text("Payment corrected", "Payment {{ receipt_number }} of {{ amount }} was reversed: {{ reason }}."),
        EM: Text("Payment corrected", "Payment {{ receipt_number }} of {{ amount }} was reversed: {{ reason }}.\n\n{{ link }}"),
        WA: Text("", f"{D}: payment {{{{ receipt_number }}}} of {{{{ amount }}}} was reversed: {{{{ reason }}}}.", ("distributor", "receipt_number", "amount", "reason")),
    },
    "payment.handed_over": {
        IN: Text("Collection handed over", "{{ receipt_number }} ({{ amount }} from {{ shop }}) was marked handed over."),
        EM: Text("Collection handed over", "{{ receipt_number }} ({{ amount }} from {{ shop }}) was marked handed over.\n\n{{ link }}"),
        WA: Text("", f"{D}: {{{{ receipt_number }}}} ({{{{ amount }}}} from {{{{ shop }}}}) was marked handed over.", ("distributor", "receipt_number", "amount", "shop")),
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
    "handover.reminder": {
        IN: Text("{{ amount }} not handed over", "{{ salesman }} has {{ count }} collections ({{ amount }}) not handed over; the oldest is from {{ oldest }}."),
        EM: Text("Collections not handed over", "{{ salesman }} has {{ count }} collections ({{ amount }}) not handed over; the oldest is from {{ oldest }}.\n\n{{ link }}"),
        WA: Text("", f"{D}: {{{{ count }}}} collections ({{{{ amount }}}}) are not handed over yet; the oldest is from {{{{ oldest }}}}.", ("distributor", "count", "amount", "oldest")),
    },
    "tax.rate_change_upcoming": {
        IN: Text("GST changes on {{ change_date }}", "The GST rate of {{ count }} products changes on {{ change_date }}: {{ products }}."),
        EM: Text("GST changes on {{ change_date }}", "The GST rate of {{ count }} products changes on {{ change_date }}: {{ products }}.\n\n{{ link }}"),
        WA: Text("", f"{D}: the GST rate of {{{{ count }}}} products changes on {{{{ change_date }}}}.", ("distributor", "count", "change_date")),
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
}  # fmt: skip


def whatsapp_template_name(event_code: str) -> str:
    """The name the provider approves for this event's template (platform number)."""
    return "b2b_" + event_code.replace(".", "_")
