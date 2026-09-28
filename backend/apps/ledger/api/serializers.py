"""Receivables, statements and adjustments (PLAN §3.10). Every figure comes from the ledger."""

from typing import Any

from rest_framework import serializers

from apps.ledger.models import EntryType, LedgerAdjustment
from apps.pricing.api.serializers import ShopRefSerializer, money


class BucketsSerializer(serializers.Serializer[Any]):
    not_due = money(help_text="Only when ageing by days past the due date.")
    d0_30 = money()
    d31_60 = money()
    d61_90 = money()
    d90_plus = money()


class ReceivableRowSerializer(serializers.Serializer[Any]):
    retailer = ShopRefSerializer()
    salesperson_name = serializers.CharField()
    credit_limit = money(allow_null=True)
    buckets = BucketsSerializer()
    owed = money(help_text="Every due's balance.")
    overdue = money(help_text="Past its due date.")
    unapplied_credit = money(help_text="Money paid or credited, not yet used.")
    net = money(help_text="Owed minus unused credit (the ledger balance).")
    oldest_due = serializers.DateField(allow_null=True, help_text="Earliest overdue due date.")
    days_overdue = serializers.IntegerField()
    last_payment_date = serializers.DateField(allow_null=True)
    last_payment_amount = money(allow_null=True)


class ReceivablesTotalsSerializer(serializers.Serializer[Any]):
    buckets = BucketsSerializer()
    owed = money()
    overdue = money()
    unapplied_credit = money()
    net = money()
    shops = serializers.IntegerField()


class ReceivablesPageSerializer(serializers.Serializer[Any]):
    basis = serializers.ChoiceField(choices=["INVOICE_DATE", "DUE_DATE"])
    totals = ReceivablesTotalsSerializer()
    count = serializers.IntegerField(help_text="Shops in the table (every page).")
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    results = ReceivableRowSerializer(many=True)


class ReceivablesSummarySerializer(serializers.Serializer[Any]):
    owed = money()
    overdue = money()
    shops_overdue = serializers.IntegerField()
    due_this_week = money()
    unapplied_credit = money()
    collections_pending_handover = money(
        allow_null=True, help_text="With salesmen, not yet handed over (payments.record only)."
    )


class PositionSerializer(serializers.Serializer[Any]):
    balance = money(help_text="Net: owed minus unused credit.")
    owed = money()
    overdue = money()
    unapplied_credit = money()
    oldest_due = serializers.DateField(allow_null=True)
    days_overdue = serializers.IntegerField()


class StatementLineSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    entry_date = serializers.DateField()
    entry_type = serializers.ChoiceField(choices=EntryType.choices)
    reference_type = serializers.ChoiceField(
        choices=["INVOICE", "CREDIT_NOTE", "PAYMENT", "ADJUSTMENT"]
    )
    reference_id = serializers.UUIDField()
    reference_number = serializers.CharField()
    narration = serializers.CharField()
    debit = money()
    credit = money()
    balance = money(help_text="Running balance after this entry.")


class StatementSerializer(serializers.Serializer[Any]):
    retailer = ShopRefSerializer()
    position = PositionSerializer()
    credit_held_while_advances_off = money(allow_null=True)
    credit_limit = money(allow_null=True)
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    opening_balance = money()
    lines = StatementLineSerializer(many=True)
    total_debits = money()
    total_credits = money()
    closing_balance = money()


class DueSerializer(serializers.Serializer[Any]):
    kind = serializers.ChoiceField(choices=["INVOICE", "ADJUSTMENT"])
    id = serializers.UUIDField()
    number = serializers.CharField()
    document_date = serializers.DateField()
    due_date = serializers.DateField()
    amount = money()
    balance_due = money()


class MoneySourceSerializer(serializers.Serializer[Any]):
    source_type = serializers.ChoiceField(choices=["PAYMENT", "CREDIT_NOTE", "ADJUSTMENT"])
    id = serializers.UUIDField()
    number = serializers.CharField()
    date = serializers.DateField()
    amount = money()
    unapplied_amount = money()


class DuesSerializer(serializers.Serializer[Any]):
    position = PositionSerializer()
    credit_held_while_advances_off = money(
        allow_null=True,
        help_text="Unused credit the shop has although advances are off (for example a cheque "
        "that cleared after its bills were paid); null when advances are on or there is none.",
    )
    financial_year_start = serializers.DateField(
        help_text="Payments dated before this belong to an earlier financial year."
    )
    dues = DueSerializer(many=True)
    unused_money = MoneySourceSerializer(many=True)


class LedgerAdjustmentCreateSerializer(serializers.Serializer[Any]):
    retailer = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=LedgerAdjustment.Kind.choices)
    amount = money(min_value=0)
    date = serializers.DateField(help_text="For an old bill: the original bill date.")
    due_date = serializers.DateField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Debits only; the shop's payment terms after the date if empty.",
    )
    bill_number = serializers.CharField(
        max_length=40, required=False, allow_blank=True, default="", help_text="Old bills only."
    )
    narration = serializers.CharField(max_length=300)


class LedgerAdjustmentSerializer(serializers.ModelSerializer[LedgerAdjustment]):
    retailer_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=LedgerAdjustment.Kind.choices)
    amount = money()
    balance_due = money()
    unapplied_amount = money()

    class Meta:
        model = LedgerAdjustment
        fields = [
            "id",
            "retailer_id",
            "kind",
            "amount",
            "adjustment_date",
            "due_date",
            "bill_number",
            "narration",
            "balance_due",
            "unapplied_amount",
        ]
