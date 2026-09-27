"""The cart as the shop (or a staff member ordering for it) sees it: server prices, tax estimate,
what can be sent now and what later, problems to fix, and the credit note. The frontend only
renders this (thin client)."""

from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.api.serializers import first_ready_thumb
from apps.inventory.availability import LABELS
from apps.orders.quote import Quote, QuoteLine
from apps.pricing.api.serializers import money, qty


class ProblemSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    details = serializers.DictField()
    blocking = serializers.BooleanField()


class QuoteUnitSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    name = serializers.CharField()
    allows_decimal = serializers.BooleanField()


class QuoteProductSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    code = serializers.CharField()
    name = serializers.CharField()
    unit = QuoteUnitSerializer()
    pack_unit = QuoteUnitSerializer(allow_null=True)
    pack_size = qty(allow_null=True)
    min_order_qty = qty()
    order_multiple = qty()
    thumbnail_url = serializers.SerializerMethodField()

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_thumbnail_url(self, product: Any) -> str | None:
        return first_ready_thumb(product)


class QuoteStockSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=LABELS)
    quantity = qty(allow_null=True)


class QuoteLineSerializer(serializers.Serializer[Any]):
    product_id = serializers.UUIDField()
    product = QuoteProductSerializer(allow_null=True)
    quantity = qty(source="qty")
    unit_price = serializers.SerializerMethodField()
    discount_total = serializers.SerializerMethodField()
    discount_percent = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField(help_text="Incl. tax, estimated.")
    ready_qty = qty(help_text="Can be sent now (estimate; final when the order is placed).")
    later_qty = qty(help_text="Goes on backorder (or is dropped when backorders are off).")
    stock = QuoteStockSerializer(allow_null=True)
    problems = ProblemSerializer(many=True)

    @extend_schema_field(money(allow_null=True))
    def get_unit_price(self, line: QuoteLine) -> str | None:
        return None if line.price is None else f"{line.price.unit_price:.2f}"

    @extend_schema_field(money(allow_null=True))
    def get_discount_total(self, line: QuoteLine) -> str | None:
        return None if line.price is None else f"{line.price.discount_total:.2f}"

    @extend_schema_field(serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True))
    def get_discount_percent(self, line: QuoteLine) -> str | None:
        return None if line.price is None else f"{line.price.discount_percent:.2f}"

    @extend_schema_field(money(allow_null=True))
    def get_line_total(self, line: QuoteLine) -> str | None:
        return None if line.tax is None else f"{line.tax.line_total:.2f}"


class QuoteTotalsSerializer(serializers.Serializer[Any]):
    gross = money()
    discount = money()
    taxable = money()
    tax = money()
    round_off = money()
    grand_total = money()


class CreditSerializer(serializers.Serializer[Any]):
    limit = money(allow_null=True)
    available = money(allow_null=True, help_text="Before this order; null without a limit.")
    outcome = serializers.ChoiceField(choices=["OK", "NEEDS_APPROVAL", "BLOCKED"])


class DeliveryAddressSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    kind = serializers.CharField()
    name = serializers.CharField(source="label", help_text="The shop's name for the address.")
    line1 = serializers.CharField()
    line2 = serializers.CharField()
    city = serializers.CharField()
    pincode = serializers.CharField()
    state = serializers.CharField(source="state.name")
    is_default = serializers.BooleanField()


class QuoteSerializer(serializers.Serializer[Any]):
    lines = QuoteLineSerializer(many=True)
    item_count = serializers.IntegerField()
    totals = serializers.SerializerMethodField()
    prices_include_gst = serializers.BooleanField()
    backorders_enabled = serializers.BooleanField(source="rules.backorders_enabled")
    credit = serializers.SerializerMethodField()
    problems = ProblemSerializer(many=True)
    can_place = serializers.BooleanField()
    address_id = serializers.UUIDField(source="address.pk", allow_null=True, default=None)
    expected_total = money(
        source="totals.grand_total", help_text="Send back when placing: a price change is caught."
    )

    @extend_schema_field(QuoteTotalsSerializer())
    def get_totals(self, quote: Quote) -> dict[str, Any]:
        t = quote.totals
        taxed = [line.tax for line in quote.lines if line.tax is not None]
        gross = sum((tax.gross_excl for tax in taxed), Decimal("0.00"))
        discount = sum((tax.discount_excl for tax in taxed), Decimal("0.00"))
        return dict(
            QuoteTotalsSerializer(
                {
                    "gross": gross,
                    "discount": discount,
                    "taxable": t.taxable,
                    "tax": t.cgst + t.sgst + t.igst + t.cess,
                    "round_off": t.round_off,
                    "grand_total": t.grand_total,
                }
            ).data
        )

    @extend_schema_field(CreditSerializer())
    def get_credit(self, quote: Quote) -> dict[str, Any]:
        c = quote.credit
        return dict(
            CreditSerializer(
                {"limit": c.limit, "available": c.available, "outcome": c.outcome}
            ).data
        )
