"""Issuing tax invoices (PLAN §4.4, spec 5.10, ADR-007/009/010/011/022/046).

One invoice per shipment, issued at dispatch (default: the packed quantity) or at acceptance and
backorder allocation (the allocated quantity), per the order's snapshot of ⚙ invoicing.timing.
Idempotent per shipment. Callers hold the shop's account (L1), the order (L2) and, at dispatch,
the stock rows (L3); the number series (L6) is taken last.

- Tax at the rate valid on the invoice date; a line is flagged when it differs from the order.
- Prices are read with the order's ⚙ tax.prices_include_gst; rounding follows the settings in
  force now, saved on the invoice.
- Place of supply and supply type come from the order (the shipping address's state).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import F

from apps.accounts.models import User
from apps.billing import numbering
from apps.billing.models import DocumentType, Invoice, InvoiceLine
from apps.billing.tax import (
    ComponentRounding,
    RoundOffMethod,
    SupplyType,
    amount_in_words,
    compute_document,
    compute_line,
    due_date,
    round2,
)
from apps.catalog.selectors import tax_rates_on
from apps.ledger import allocation
from apps.ledger import services as ledger
from apps.ledger.models import EntryType
from apps.orders.models import Fulfilment, FulfilmentLine, Order, OrderLine
from apps.platform.models import Tenant, TenantProfile
from apps.platform.selectors import get_setting
from common import outbox
from common.dates import today_ist
from common.tenancy import require_tenant_id

ZERO = Decimal("0")
ROUNDING_KEYS = ("tax.component_rounding", "invoicing.round_to_rupee", "invoicing.round_off_method")


def rounding_snapshot(tenant_id: Any) -> dict[str, Any]:
    """The rounding settings in force now, saved on each invoice and credit note."""
    return {key: get_setting(key, tenant_id) for key in ROUNDING_KEYS}


def seller_snapshot(tenant: Tenant) -> dict[str, Any]:
    profile = TenantProfile.objects.filter(tenant=tenant).first()
    return {
        "legal_name": tenant.legal_name,
        "trade_name": tenant.name,
        "gstin": tenant.gstin,
        "pan": tenant.pan,
        "address": ", ".join(
            x for x in (tenant.address_line1, tenant.address_line2, tenant.city) if x
        )
        + f" - {tenant.pincode}",
        "state_code": tenant.state_id,
        "state": tenant.state.name,
        "phone": tenant.phone,
        "email": tenant.email,
        "bank": {
            "account_name": profile.bank_account_name if profile else "",
            "account_number": profile.bank_account_number if profile else "",
            "ifsc": profile.bank_ifsc if profile else "",
            "bank_name": profile.bank_name if profile else "",
            "branch": profile.bank_branch if profile else "",
            "upi_id": profile.upi_id if profile else "",
        },
        "terms": profile.invoice_terms if profile else "",
        "footer": profile.invoice_footer if profile else "",
        "signatory": profile.signatory_name if profile else "",
        "signatory_image": profile.signatory_image if profile else "",
    }


def buyer_snapshot(order: Order) -> dict[str, Any]:
    shop = order.retailer
    return {
        "name": shop.shop_name,
        "code": shop.code,
        "contact": shop.owner_name,
        "phone": shop.mobile,
        "gstin": shop.gstin or "",
        "state_code": shop.state_id,
        "billing_address": order.billing_address,
        "shipping_address": order.shipping_address,
    }


@dataclass(frozen=True)
class _Planned:
    fl: FulfilmentLine
    line: OrderLine
    quantity: Decimal
    discount: Decimal
    rate: Decimal
    cess_rate: Decimal


def _quantity(fl: FulfilmentLine, trigger: str) -> Decimal:
    """At dispatch the packed quantity; otherwise what the shipment holds."""
    if fl.cancelled_by_retailer_at is not None:
        return ZERO
    if trigger in (Invoice.Trigger.ON_DISPATCH, Invoice.Trigger.AFTER_DISPATCH):
        return Decimal(fl.qty_packed if fl.qty_packed is not None else fl.quantity)
    return Decimal(fl.quantity)


def _discount(fl: FulfilmentLine, line: OrderLine, quantity: Decimal, rounding: str) -> Decimal:
    """The line's discount for the invoiced quantity: the discount earned when ordering, in
    proportion (or, for a repriced backorder shipment, the discount at today's price)."""
    mode = ComponentRounding(rounding)
    if fl.discount_amount is not None:  # repriced (ADR-021): resolved with today's price
        return round2(Decimal(fl.discount_amount) * quantity / Decimal(fl.quantity), mode)
    if not line.discount_amount:
        return ZERO
    return round2(Decimal(line.discount_amount) * quantity / Decimal(line.qty_ordered), mode)


def issue_invoice_for_fulfilment(
    shipment: Fulfilment, *, trigger: str, by: User | None, on: date | None = None
) -> Invoice | None:
    """Issue the shipment's tax invoice (or return the one it has). ``None`` when nothing in it
    is to be invoiced (everything declined or packed as zero)."""
    existing: Invoice | None = Invoice.objects.filter(fulfilment=shipment).first()
    if existing is not None:
        return existing
    order: Order = Order.objects.select_related("retailer", "place_of_supply").get(
        pk=shipment.order_id
    )
    tenant_id = require_tenant_id()
    invoice_date = on or today_ist()
    snapshot = rounding_snapshot(tenant_id)
    rounding = ComponentRounding(snapshot["tax.component_rounding"])
    lines = list(
        FulfilmentLine.objects.filter(fulfilment=shipment)
        .select_related("order_line", "product")
        .order_by("order_line__line_no")
    )
    rates = tax_rates_on([fl.product_id for fl in lines], invoice_date)
    planned: list[_Planned] = []
    for fl in lines:
        quantity = _quantity(fl, trigger)
        if quantity <= 0:
            continue
        line = fl.order_line
        rate_row = rates.get(fl.product_id)
        rate = Decimal(rate_row.gst_rate) if rate_row else Decimal(line.gst_rate)
        cess = Decimal(rate_row.cess_rate) if rate_row else Decimal(line.cess_rate)
        planned.append(
            _Planned(fl, line, quantity, _discount(fl, line, quantity, rounding), rate, cess)
        )
    if not planned:
        return None

    account = ledger.lock_account(order.retailer_id)  # L1 (already held by the caller)
    supply = SupplyType(order.supply_type)
    taxes = [
        compute_line(
            qty=p.quantity,
            unit_price=Decimal(p.fl.unit_price),
            rate=p.rate,
            supply_type=supply,
            discount_amount=p.discount,
            cess_rate=p.cess_rate,
            inclusive=order.prices_include_tax,
            rounding=rounding,
        )
        for p in planned
    ]
    totals = compute_document(
        taxes,
        round_to_rupee=bool(snapshot["invoicing.round_to_rupee"]),
        round_off_method=RoundOffMethod(snapshot["invoicing.round_off_method"]),
    )
    differs = [p.rate != Decimal(p.line.gst_rate) for p in planned]
    tenant = Tenant.objects.select_related("state").get(pk=tenant_id)
    series, number = numbering.next_number(DocumentType.INVOICE, invoice_date)  # L6
    invoice: Invoice = Invoice.objects.create(
        number=number,
        series=series,
        fy=series.fy,
        retailer_id=order.retailer_id,
        seller=seller_snapshot(tenant),
        buyer=buyer_snapshot(order),
        place_of_supply_id=order.place_of_supply_id,
        supply_type=order.supply_type,
        prices_include_tax=order.prices_include_tax,
        settings_snapshot=snapshot,
        gross_total=sum((t.gross_excl for t in taxes), ZERO),
        discount_total=sum((t.discount_excl for t in taxes), ZERO),
        taxable_total=totals.taxable,
        cgst_total=totals.cgst,
        sgst_total=totals.sgst,
        igst_total=totals.igst,
        cess_total=totals.cess,
        round_off=totals.round_off,
        grand_total=totals.grand_total,
        amount_in_words=amount_in_words(totals.grand_total),
        issued_by=by,
        invoice_date=invoice_date,
        due_date=due_date(invoice_date, order.retailer.payment_terms_days),
        order=order,
        fulfilment=shipment,
        issued_trigger=trigger,
        rate_differs_from_order=any(differs),
        balance_due=totals.grand_total,
    )
    InvoiceLine.objects.bulk_create(
        [
            InvoiceLine(
                tenant_id=tenant_id,  # bulk_create skips TenantScopedModel.save
                invoice=invoice,
                line_no=index,
                order_line=p.line,
                fulfilment_line=p.fl,
                product_id=p.fl.product_id,
                description=p.line.product_name,
                product_code=p.line.product_code,
                hsn_code=p.line.hsn_code,
                unit_code=p.line.unit_code,
                quantity=p.quantity,
                unit_price=p.fl.unit_price,
                gross_amount=tax.gross_excl,
                discount_amount=tax.discount_excl,
                taxable_value=tax.taxable,
                gst_rate=p.rate,
                cgst_rate=tax.cgst_rate,
                cgst_amount=tax.cgst,
                sgst_rate=tax.sgst_rate,
                sgst_amount=tax.sgst,
                igst_rate=tax.igst_rate,
                igst_amount=tax.igst,
                cess_rate=p.cess_rate,
                cess_amount=tax.cess,
                line_total=tax.line_total,
                order_rate=p.line.gst_rate,
                rate_differs_from_order=differ,
            )
            for index, (p, tax, differ) in enumerate(zip(planned, taxes, differs, strict=True), 1)
        ]
    )
    for p in planned:
        OrderLine.objects.filter(pk=p.line.pk).update(qty_invoiced=F("qty_invoiced") + p.quantity)
    ledger.post(
        account,
        EntryType.INVOICE,
        debit=invoice.grand_total,
        entry_date=invoice_date,
        ref=ledger.Reference("INVOICE", invoice.pk, number),
        narration=f"Invoice for order {order.number}",
        by=by,
    )
    allocation.settle(account, by=by)  # advances and unused credit, oldest money first
    invoice.refresh_from_db()
    outbox.emit(
        "invoice.issued",
        aggregate_type="Invoice",
        aggregate_id=invoice.pk,
        payload={
            "invoice_id": str(invoice.pk),
            "number": number,
            "order_id": str(order.pk),
            "order_number": order.number,
            "retailer_id": str(order.retailer_id),
            "grand_total": f"{invoice.grand_total:.2f}",
            "rate_differs_from_order": invoice.rate_differs_from_order,
        },
    )
    return invoice


def timing(order: Order) -> str:
    """The order's snapshot of ⚙ invoicing.timing (orders placed before Phase 5 have one too)."""
    return str(order.settings_snapshot.get("invoicing.timing", "ON_DISPATCH"))
