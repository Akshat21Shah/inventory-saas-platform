"""Invoices for money tests: an order placed, accepted, packed in full and dispatched."""

from typing import Any

from apps.billing.models import Invoice
from apps.orders import fulfilment, transitions
from apps.orders.fulfilment import Transport
from apps.orders.models import Fulfilment
from apps.orders.tests.helpers import place
from common.tenancy import tenant_context

NO_TRANSPORT = Transport("", "", "")


def ship_invoice(tenant: Any, shop: Any, by: Any, *lines: tuple[Any, str]) -> Invoice:
    order = place(tenant, shop, *lines)
    with tenant_context(tenant.pk):
        transitions.accept_order(order.pk, by=by)
        shipment = Fulfilment.objects.get(order=order)
        fulfilment.pack(shipment.pk, {}, by=by)
        fulfilment.dispatch(shipment.pk, NO_TRANSPORT, by=by)
        invoice: Invoice = Invoice.objects.get(fulfilment=shipment)
        return invoice
