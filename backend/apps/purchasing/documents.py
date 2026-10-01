"""The purchase order's printed copies (ADR-053 item 5): the supplier's copy with costs (emailed
and shared) and a copy without them for staff who can't see costs. Printed after every change,
in the background, like the billing documents."""

from typing import Any
from uuid import UUID

from django.template.loader import render_to_string
from django.utils import timezone

from apps.billing.documents import PDF, document_key
from apps.billing.invoicing import seller_snapshot
from apps.billing.models import PdfStatus
from apps.billing.pdf import get_renderer
from apps.platform.models import Tenant
from apps.purchasing.models import PurchaseOrder
from common.storage import get_storage
from common.tenancy import require_tenant_id, tenant_transaction


def context(order: PurchaseOrder, *, prices: bool) -> dict[str, Any]:
    tenant = Tenant.objects.select_related("state").get(pk=order.tenant_id)
    supplier = order.supplier
    party = order.supplier_snapshot or {
        "name": supplier.name,
        "gstin": supplier.gstin or "",
        "contact_name": supplier.contact_name,
        "phone": supplier.phone,
        "email": supplier.email,
        "address": ", ".join(
            x
            for x in (
                supplier.address_line1,
                supplier.address_line2,
                supplier.city,
                supplier.pincode,
            )
            if x
        ),
    }
    return {
        "doc": order,
        "seller": seller_snapshot(tenant),
        "supplier": party,
        "lines": list(order.lines.all()),
        "prices": prices,
        "printed_at": timezone.now(),
    }


def render_order(order_id: UUID) -> None:
    tenant_id = require_tenant_id()
    with tenant_transaction(tenant_id):
        order = PurchaseOrder.objects.select_related("supplier").get(pk=order_id)
        priced = render_to_string("purchasing/purchase_order.html", context(order, prices=True))
        plain = render_to_string("purchasing/purchase_order.html", context(order, prices=False))
        key = document_key(tenant_id, "purchase-orders", order.number)
        plain_key = document_key(tenant_id, "purchase-orders", order.number, "-no-prices")
    renderer = get_renderer()
    get_storage().put(key, renderer.render(priced), PDF)
    get_storage().put(plain_key, renderer.render(plain), PDF)
    with tenant_transaction(tenant_id):
        PurchaseOrder.objects.filter(pk=order_id).update(
            pdf_key=key, plain_pdf_key=plain_key, pdf_status=PdfStatus.READY
        )


def mark_failed(order_id: UUID) -> None:
    with tenant_transaction(require_tenant_id()):
        PurchaseOrder.objects.filter(pk=order_id).update(pdf_status=PdfStatus.FAILED)
