"""The ledger's invariants (PLAN §4.5), checked after every money test and in the
reconciliation property test: balance = invoices - credited payments - credit notes
± adjustments + refunds not reversed = what is owed - unused credit."""

from decimal import Decimal
from typing import Any

from django.db.models import Sum

from apps.billing.models import CreditNote, Invoice
from apps.ledger.models import Allocation, LedgerAdjustment, LedgerEntry, RetailerAccount
from apps.payments.models import Payment, Refund
from common.tenancy import tenant_context

ZERO = Decimal("0")


def _sum(qs: Any, field: str) -> Decimal:
    return Decimal(qs.aggregate(total=Sum(field))["total"] or 0)


def check_ledger(tenant: Any) -> None:
    """For every shop: the balance is the sum of its entries, the last entry's balance, invoices
    minus payments minus credit notes plus/minus adjustments, and what is still owed minus the
    unused credit. Every invoice and source agrees with its allocations."""
    with tenant_context(tenant.pk):
        for account in RetailerAccount.objects.all():
            shop = account.retailer_id
            entries = LedgerEntry.objects.filter(account=account)
            debits, credits = _sum(entries, "debit"), _sum(entries, "credit")
            assert account.balance == account.total_debits - account.total_credits
            assert (account.total_debits, account.total_credits) == (debits, credits), shop
            last = entries.order_by("-created_at", "-id").first()
            assert account.balance == (last.balance_after if last else ZERO), shop

            invoices = Invoice.objects.filter(retailer_id=shop, status="ISSUED")
            notes = CreditNote.objects.filter(retailer_id=shop, status="ISSUED")
            credited_payments = Payment.objects.filter(retailer_id=shop, credited=True)
            adjustments = LedgerAdjustment.objects.filter(retailer_id=shop)
            debit_adj = adjustments.filter(kind__in=("OPENING_DEBIT", "DEBIT"))
            credit_adj = adjustments.filter(kind__in=("OPENING_CREDIT", "CREDIT"))
            refunds = Refund.objects.filter(retailer_id=shop)
            live_refunds = refunds.filter(status="ISSUED")  # a reversal's credit cancels it
            expected = (
                _sum(invoices, "grand_total")
                - _sum(credited_payments, "amount")
                - _sum(notes, "grand_total")
                + _sum(debit_adj, "amount")
                - _sum(credit_adj, "amount")
                + _sum(live_refunds, "amount")
            )
            assert account.balance == expected, (shop, account.balance, expected)

            unapplied = (
                _sum(credited_payments, "unapplied_amount")
                + _sum(notes, "unapplied_amount")
                + _sum(credit_adj, "unapplied_amount")
            )
            assert account.unapplied_credit == unapplied, shop
            owed = (
                _sum(invoices, "balance_due")
                + _sum(debit_adj, "balance_due")
                + _sum(refunds, "balance_due")
            )
            assert account.balance == owed - unapplied, (shop, account.balance, owed, unapplied)

            for invoice in invoices:
                allocated = _sum(Allocation.objects.filter(invoice=invoice), "amount")
                assert invoice.balance_due == invoice.grand_total - allocated, invoice.number
                assert invoice.amount_paid + invoice.amount_credited == allocated
            for payment in Payment.objects.filter(retailer_id=shop):
                used = _sum(Allocation.objects.filter(payment=payment), "amount")
                left = payment.amount - used if payment.credited else ZERO
                assert payment.unapplied_amount == left, payment.number
            for note in notes:
                used = _sum(Allocation.objects.filter(credit_note=note), "amount")
                assert note.unapplied_amount == note.grand_total - used, note.number
            for adj in debit_adj:
                used = _sum(Allocation.objects.filter(debit_adjustment=adj), "amount")
                assert adj.balance_due == adj.amount - used
            for adj in credit_adj:
                used = _sum(Allocation.objects.filter(credit_adjustment=adj), "amount")
                assert adj.unapplied_amount == adj.amount - used
            for refund in refunds:  # covered by credit; owed again if that money is undone
                covered = _sum(Allocation.objects.filter(refund=refund), "amount")
                if refund.status == "REVERSED":  # its credit is back and nothing is owed
                    assert (refund.balance_due, covered) == (ZERO, ZERO), refund.number
                else:
                    assert refund.balance_due == refund.amount - covered, refund.number
