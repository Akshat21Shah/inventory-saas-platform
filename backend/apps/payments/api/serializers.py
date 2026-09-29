"""Payments, collections and allocations (PLAN §3.10, ADR-046 items 6 and 10)."""

from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.billing.api.serializers import AppliedSerializer, UsedForSerializer
from apps.billing.models import PdfStatus
from apps.billing.tax import fy_start
from apps.payments.models import MANUAL_MODES, Payment, PaymentIntent, Refund
from apps.platform.selectors import get_setting
from apps.pricing.api.serializers import ShopRefSerializer, money
from common.dates import to_ist


class PaymentRowSerializer(serializers.ModelSerializer[Payment]):
    retailer = ShopRefSerializer()
    amount = money()
    mode = serializers.ChoiceField(choices=Payment.Mode.choices)
    status = serializers.ChoiceField(choices=Payment.Status.choices)
    credit_timing = serializers.ChoiceField(choices=Payment.CreditTiming.choices)
    handover_status = serializers.ChoiceField(choices=Payment.Handover.choices)
    unapplied_amount = money(help_text="Credited but not yet matched to dues.")
    collected_by_name = serializers.SerializerMethodField()
    receipt_pdf_status = serializers.ChoiceField(choices=PdfStatus.choices)
    dated_in_previous_financial_year = serializers.SerializerMethodField()
    held_as_credit_while_advances_off = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id",
            "number",
            "payment_date",
            "retailer",
            "amount",
            "mode",
            "status",
            "credit_timing",
            "credited",
            "unapplied_amount",
            "reference_no",
            "cheque_number",
            "handover_status",
            "collected_by_name",
            "receipt_pdf_status",
            "dated_in_previous_financial_year",
            "held_as_credit_while_advances_off",
        ]

    def get_dated_in_previous_financial_year(self, payment: Payment) -> bool:
        """The receipt is numbered in the year it was recorded; the payment is accounted on its
        own date, which here falls in an earlier financial year (2026-09-28)."""
        return fy_start(payment.payment_date) < fy_start(to_ist(payment.created_at).date())

    @extend_schema_field(money(allow_null=True))
    def get_held_as_credit_while_advances_off(self, payment: Payment) -> str | None:
        """Money of this payment kept as credit although advances are off."""
        if payment.unapplied_amount <= 0 or get_setting("payments.hold_advances"):
            return None
        return f"{Decimal(payment.unapplied_amount):.2f}"

    def get_collected_by_name(self, payment: Payment) -> str:
        return payment.collected_by.full_name if payment.collected_by else ""


class PaymentDetailSerializer(PaymentRowSerializer):
    recorded_by_name = serializers.SerializerMethodField()
    handed_over_by_name = serializers.SerializerMethodField()
    used_for = UsedForSerializer(many=True, source="used_for_rows")

    class Meta(PaymentRowSerializer.Meta):
        fields = [
            *PaymentRowSerializer.Meta.fields,
            "cheque_date",
            "bank_name",
            "notes",
            "recorded_by_name",
            "handed_over_at",
            "handed_over_by_name",
            "cleared_at",
            "reversed_at",
            "reversal_reason",
            "used_for",
            "gateway_payment_id",
            "needs_review",
            "review_reason",
            "reviewed_at",
        ]

    def get_recorded_by_name(self, payment: Payment) -> str:
        return payment.recorded_by.full_name if payment.recorded_by else ""

    def get_handed_over_by_name(self, payment: Payment) -> str:
        return payment.handed_over_by.full_name if payment.handed_over_by else ""


class ShopPaymentDetailSerializer(PaymentDetailSerializer):
    """The shop's view: without the office's review of online payments."""

    class Meta(PaymentDetailSerializer.Meta):
        fields = [
            f
            for f in PaymentDetailSerializer.Meta.fields
            if f not in ("needs_review", "review_reason", "reviewed_at")
        ]


class DueAmountSerializer(serializers.Serializer[Any]):
    target_type = serializers.ChoiceField(choices=["INVOICE", "ADJUSTMENT"])
    target_id = serializers.UUIDField()
    amount = money(min_value=0)


class CollectSerializer(serializers.Serializer[Any]):
    retailer = serializers.UUIDField()
    amount = money(min_value=0)
    mode = serializers.ChoiceField(choices=MANUAL_MODES)
    payment_date = serializers.DateField()
    reference_no = serializers.CharField(
        max_length=60, required=False, allow_blank=True, default=""
    )
    cheque_number = serializers.CharField(
        max_length=20, required=False, allow_blank=True, default=""
    )
    cheque_date = serializers.DateField(required=False, allow_null=True, default=None)
    bank_name = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class RecordPaymentSerializer(CollectSerializer):
    pay_first = DueAmountSerializer(
        many=True,
        required=False,
        default=list,
        help_text="Dues to pay first; the rest goes to the earliest dues, then is kept as credit.",
    )


class PaymentAllocateSerializer(serializers.Serializer[Any]):
    to = DueAmountSerializer(many=True)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class ReallocateSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(max_length=300)
    to = DueAmountSerializer(
        many=True,
        required=False,
        default=list,
        help_text="Where the money goes instead; leave empty to keep it as unused credit.",
    )


class ClearSerializer(serializers.Serializer[Any]):
    on = serializers.DateField(required=False, allow_null=True, default=None)


class PaymentReasonSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(max_length=300)


class HandoverSerializer(serializers.Serializer[Any]):
    payments = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=500)


class HandoverResultSerializer(serializers.Serializer[Any]):
    payments = PaymentRowSerializer(many=True)


class PendingHandoverSerializer(serializers.Serializer[Any]):
    salesman_id = serializers.UUIDField()
    salesman_name = serializers.CharField()
    count = serializers.IntegerField()
    amount = money()
    oldest = serializers.DateField()


class ReallocationResultSerializer(serializers.Serializer[Any]):
    reversal = UsedForSerializer()
    reallocated = UsedForSerializer(many=True)


class RefundSerializer(serializers.ModelSerializer[Refund]):
    retailer = ShopRefSerializer()
    amount = money()
    mode = serializers.ChoiceField(choices=Refund.Mode.choices)
    voucher_pdf_status = serializers.ChoiceField(choices=PdfStatus.choices)
    recorded_by_name = serializers.SerializerMethodField()
    status = serializers.ChoiceField(choices=Refund.Status.choices)

    class Meta:
        model = Refund
        fields = [
            "id",
            "number",
            "refund_date",
            "retailer",
            "amount",
            "mode",
            "status",
            "reference_no",
            "notes",
            "recorded_by_name",
            "voucher_pdf_status",
            "reversed_at",
            "reversal_reason",
        ]

    def get_recorded_by_name(self, refund: Refund) -> str:
        return refund.recorded_by.full_name if refund.recorded_by else ""


class RefundDetailSerializer(RefundSerializer):
    paid_from = AppliedSerializer(many=True, source="paid_from_rows")

    class Meta(RefundSerializer.Meta):
        fields = [*RefundSerializer.Meta.fields, "paid_from"]


class RefundCreateSerializer(serializers.Serializer[Any]):
    retailer = serializers.UUIDField()
    amount = money(min_value=0)
    mode = serializers.ChoiceField(choices=Refund.Mode.choices)
    refund_date = serializers.DateField()
    reference_no = serializers.CharField(
        max_length=60, required=False, allow_blank=True, default=""
    )
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class ReviewSerializer(serializers.Serializer[Any]):
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class CheckoutInputSerializer(serializers.Serializer[Any]):
    purpose = serializers.ChoiceField(choices=PaymentIntent.Purpose.choices)
    invoice_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    amount = money(required=False, allow_null=True, default=None)


class CheckoutSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    purpose = serializers.ChoiceField(choices=PaymentIntent.Purpose.choices)
    invoice_id = serializers.UUIDField(allow_null=True)
    invoice_number = serializers.CharField(allow_blank=True)
    amount = money()
    status = serializers.ChoiceField(choices=PaymentIntent.Status.choices)
    provider = serializers.CharField()
    checkout = serializers.JSONField(
        allow_null=True,
        help_text="What the page opens: the gateway's checkout options (no secrets); for the "
        "test gateway, a checkout_url.",
    )
    expires_at = serializers.DateTimeField()
    last_error = serializers.CharField(allow_blank=True)
    payment_id = serializers.UUIDField(allow_null=True)
    receipt_number = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    paid_at = serializers.DateTimeField(allow_null=True)


class CheckoutOutcomeSerializer(serializers.Serializer[Any]):
    outcome = serializers.ChoiceField(choices=["success", "failed", "dismissed"])


class PaymentIntentRowSerializer(CheckoutSerializer):
    shop_name = serializers.CharField()
    retailer_id = serializers.UUIDField()
    client_outcome = serializers.CharField(allow_blank=True)
