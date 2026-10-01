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
from apps.billing.models import DocumentStatus, DocumentType, Invoice, InvoiceLine
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
    unit_cost: Decimal | None  # the cost recorded on the invoice line (ADR-050)


def current_buyer(order: Order) -> tuple[dict[str, Any], str, str]:
    """The shop as it is now, for re-issuing a corrected invoice (Phase 7 backend checkpoint,
    change 2): its name, GSTIN and state now, its default billing address, and the order's
    delivery address as that saved address reads now (else as ordered). The place of supply
    follows the delivery address, else the shop's state. Returns (buyer, place, supply type)."""
    from apps.orders.quote import supply_type_for
    from apps.orders.services import _address_json
    from apps.retailers.models import Retailer, RetailerAddress

    shop = Retailer.objects.get(pk=order.retailer_id)
    addresses = RetailerAddress.objects.filter(retailer=shop).select_related("state")
    shipping_id = (order.shipping_address or {}).get("id")
    shipping = addresses.filter(pk=shipping_id).first() if shipping_id else None
    billing = addresses.filter(kind="BILLING", is_default=True).first()
    buyer = {
        "name": shop.shop_name,
        "code": shop.code,
        "contact": shop.owner_name,
        "phone": shop.mobile,
        "gstin": shop.gstin or "",
        "state_code": shop.state_id,
        "billing_address": _address_json(billing) if billing else order.billing_address,
        "shipping_address": _address_json(shipping) if shipping else order.shipping_address,
    }
    place = (
        shipping.state_id
        if shipping
        else (order.shipping_address or {}).get("state_code") or shop.state_id
    )
    tenant_state = str(
        Tenant.objects.filter(pk=order.tenant_id).values_list("state_id", flat=True).get()
    )
    return buyer, str(place), supply_type_for(tenant_state, str(place)).value


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
    shipment: Fulfilment,
    *,
    trigger: str,
    by: User | None,
    on: date | None = None,
    reissue_of: Invoice | None = None,
) -> Invoice | None:
    """Issue the shipment's tax invoice (or return the one it has). ``None`` when nothing in it
    is to be invoiced (everything declined or packed as zero).

    ``reissue_of``: a cancelled invoice (its IRN cancelled) re-issued for the same supply with a
    new number: the shop's current details and place of supply, but the original quantities,
    prices, discounts, GST rates and rounding (Phase 7 backend checkpoint, change 2)."""
    existing: Invoice | None = Invoice.objects.filter(
        fulfilment=shipment, status=DocumentStatus.ISSUED
    ).first()
    if existing is not None:
        return existing
    order: Order = Order.objects.select_related("retailer", "place_of_supply").get(
        pk=shipment.order_id
    )
    tenant_id = require_tenant_id()
    invoice_date = on or today_ist()
    snapshot = reissue_of.settings_snapshot if reissue_of else rounding_snapshot(tenant_id)
    rounding = ComponentRounding(snapshot["tax.component_rounding"])
    planned: list[_Planned] = []
    if reissue_of is not None:
        for old in reissue_of.lines.select_related("fulfilment_line", "order_line").order_by(
            "line_no"
        ):
            fl, line, quantity = old.fulfilment_line, old.order_line, Decimal(old.quantity)
            planned.append(
                _Planned(
                    fl,
                    line,
                    quantity,
                    _discount(fl, line, quantity, rounding),
                    Decimal(old.gst_rate),
                    Decimal(old.cess_rate),
                    old.unit_cost,  # the same supply: the same cost
                )
            )
    else:
        lines = list(
            FulfilmentLine.objects.filter(fulfilment=shipment)
            .select_related("order_line", "product")
            .order_by("order_line__line_no")
        )
        rates = tax_rates_on([fl.product_id for fl in lines], invoice_date)
        for fl in lines:
            quantity = _quantity(fl, trigger)
            if quantity <= 0:
                continue
            line = fl.order_line
            rate_row = rates.get(fl.product_id)
            rate = Decimal(rate_row.gst_rate) if rate_row else Decimal(line.gst_rate)
            cess = Decimal(rate_row.cess_rate) if rate_row else Decimal(line.cess_rate)
            planned.append(
                _Planned(
                    fl,
                    line,
                    quantity,
                    _discount(fl, line, quantity, rounding),
                    rate,
                    cess,
                    fl.product.cost_price,
                )
            )
    if not planned:
        return None

    account = ledger.lock_account(order.retailer_id)  # L1 (already held by the caller)
    if reissue_of is not None:
        buyer, place, supply_value = current_buyer(order)
    else:
        buyer, place, supply_value = (
            buyer_snapshot(order),
            order.place_of_supply_id,
            order.supply_type,
        )
    supply = SupplyType(supply_value)
    inclusive = reissue_of.prices_include_tax if reissue_of else order.prices_include_tax
    taxes = [
        compute_line(
            qty=p.quantity,
            unit_price=Decimal(p.fl.unit_price),
            rate=p.rate,
            supply_type=supply,
            discount_amount=p.discount,
            cess_rate=p.cess_rate,
            inclusive=inclusive,
            rounding=rounding,
        )
        for p in planned
    ]
    totals = compute_document(
        taxes,
        round_to_rupee=bool(snapshot["invoicing.round_to_rupee"]),
        round_off_method=RoundOffMethod(snapshot["invoicing.round_off_method"]),
    )
    # A free line carries no GST, so a rate change on it changes nothing (ADR-056 item 10).
    differs = [
        p.rate != Decimal(p.line.gst_rate) and p.line.free_of_line_id is None for p in planned
    ]
    tenant = Tenant.objects.select_related("state").get(pk=tenant_id)
    series, number = numbering.next_number(DocumentType.INVOICE, invoice_date)  # L6
    invoice: Invoice = Invoice.objects.create(
        number=number,
        series=series,
        fy=series.fy,
        retailer_id=order.retailer_id,
        seller=seller_snapshot(tenant),
        buyer=buyer,
        place_of_supply_id=place,
        supply_type=supply_value,
        prices_include_tax=inclusive,
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
                unit_cost=p.unit_cost,
                is_free=p.line.free_of_line_id is not None,
                scheme_name=p.line.scheme_name,
            )
            for index, (p, tax, differ) in enumerate(zip(planned, taxes, differs, strict=True), 1)
        ]
    )
    for p in planned:
        OrderLine.objects.filter(pk=p.line.pk).update(qty_invoiced=F("qty_invoiced") + p.quantity)
    if invoice.grand_total > 0:  # only free goods in it (ADR-056): nothing is owed
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
    from apps.compliance.einvoice import on_issued

    on_issued(invoice)  # the IRN, when e-invoicing is on and the shop has a GSTIN (ADR-049)
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
