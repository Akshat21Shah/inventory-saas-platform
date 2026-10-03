"""Printed documents in the shop's language (ADR-060 item 6): labels in English, then the shop's
language ("Tax invoice / कर बीजक"); names, numbers and the amount in words as they are.

Every label the templates print with ``{% t "…" %}`` is listed here, so the message catalogs
translate it (a test keeps this list and the templates in step). The language is fixed when a
document is issued, so a reprint is identical."""

from typing import Any

from django.utils.translation import gettext_noop

from apps.platform.selectors import get_setting
from common import languages


def language_for(retailer: Any) -> str:
    """The language a new document for this shop is printed in besides English: the shop's,
    unless the distributor prints English only (⚙ ``documents.language``)."""
    if get_setting("documents.language", retailer.tenant_id) == "ENGLISH":
        return languages.DEFAULT
    return languages.shop_language(retailer)


LABELS = (
    # Titles and copies
    gettext_noop("Tax invoice"),
    gettext_noop("Credit note"),
    gettext_noop("Payment receipt"),
    gettext_noop("Refund voucher"),
    gettext_noop("Order confirmation"),
    gettext_noop("Original for recipient"),
    gettext_noop("Duplicate for transporter"),
    gettext_noop("Triplicate for supplier"),
    gettext_noop("Issued automatically"),
    gettext_noop("Cheque bounced"),
    gettext_noop("Cancelled"),
    gettext_noop("Reversed"),
    gettext_noop("This is not a tax invoice."),
    # Details
    gettext_noop("Invoice no."),
    gettext_noop("Credit note no."),
    gettext_noop("Receipt no."),
    gettext_noop("Voucher no."),
    gettext_noop("Order no."),
    gettext_noop("Place of supply"),
    gettext_noop("Invoice date"),
    gettext_noop("Due date"),
    gettext_noop("Date"),
    gettext_noop("Payment date"),
    gettext_noop("Supply"),
    gettext_noop("Within the state (CGST + SGST)"),
    gettext_noop("Between states (IGST)"),
    gettext_noop("Reverse charge"),
    gettext_noop("Yes"),
    gettext_noop("No"),
    gettext_noop("Order"),
    gettext_noop("Prices"),
    gettext_noop("Including GST"),
    gettext_noop("Excluding GST"),
    gettext_noop("Against invoice"),
    gettext_noop("dated %(date)s"),
    gettext_noop("Reason"),
    gettext_noop("Placed"),
    gettext_noop("Accepted"),
    gettext_noop("Received from"),
    gettext_noop("Paid to"),
    gettext_noop("Mode"),
    gettext_noop("Cheque"),
    gettext_noop("No. %(number)s"),
    gettext_noop("Bank"),
    gettext_noop("Reference"),
    # Parties and signature
    gettext_noop("Bill to"),
    gettext_noop("Ship to"),
    gettext_noop("Unregistered"),
    gettext_noop("Bank details"),
    gettext_noop("Terms"),
    gettext_noop("For %(name)s"),
    gettext_noop("Authorised signatory"),
    gettext_noop("Received by"),
    gettext_noop("Name and signature of the shop"),
    # Lines and totals
    gettext_noop("Description"),
    gettext_noop("Item"),
    gettext_noop("Qty"),
    gettext_noop("Rate (₹)"),
    gettext_noop("Gross (₹)"),
    gettext_noop("Discount (₹)"),
    gettext_noop("Taxable (₹)"),
    gettext_noop("Amount (₹)"),
    gettext_noop("Cess"),
    gettext_noop("Cess (₹)"),
    gettext_noop("GST"),
    gettext_noop("GST rate"),
    gettext_noop("Total tax (₹)"),
    gettext_noop("Free"),
    gettext_noop("%(quantity)s to follow when stock arrives"),
    gettext_noop("Taxable value"),
    gettext_noop("Round off"),
    gettext_noop("Invoice total"),
    gettext_noop("Credit total"),
    gettext_noop("GST (estimate)"),
    gettext_noop("Estimated total"),
    gettext_noop("Amount received"),
    gettext_noop("Amount paid back"),
    gettext_noop("In words:"),
    gettext_noop("Paid against"),
    gettext_noop("Credit from"),
    gettext_noop("Paid from the shop's credit balance:"),
    gettext_noop("Kept as credit for future bills: %(amount)s"),
    # Notes
    gettext_noop("Cancelled: this invoice's IRN was cancelled."),
    gettext_noop("It is replaced by invoice %(number)s."),
    gettext_noop(
        "The GST rate on some items changed after the order was placed; this invoice uses the "
        "rate in force on the invoice date."
    ),
    gettext_noop("Cheque bounce charge of %(amount)s added to the account on %(date)s."),
    gettext_noop("Subject to the cheque being cleared by the bank."),
    gettext_noop(
        "Reversed on %(date)s: %(reason)s. The amount is back in the shop's credit balance."
    ),
    gettext_noop(
        "The amount payable is on the tax invoice. Tax is worked out at the rate in force on the "
        "invoice date."
    ),
    gettext_noop("E-way bill no."),
    gettext_noop("Valid until"),
    gettext_noop("Vehicle"),
    gettext_noop("Ack. no."),
    gettext_noop("Ack. date"),
)
