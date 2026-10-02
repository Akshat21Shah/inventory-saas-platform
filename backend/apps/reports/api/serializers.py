from typing import Any

from rest_framework import serializers

from apps.reports.models import ReportRun
from apps.reports.registry import GROUP_CHOICES, FilterKind, Kind


class ColumnSerializer(serializers.Serializer[Any]):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]  # a field, not Field.label
    kind = serializers.ChoiceField(choices=[k.value for k in Kind])
    cost = serializers.BooleanField(help_text="Shown only with permission to see costs.")
    total = serializers.BooleanField(help_text="Has a figure in the totals row.")


class FilterSerializer(serializers.Serializer[Any]):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]  # fields, not Field attributes
    kind = serializers.ChoiceField(choices=[k.value for k in FilterKind])
    required = serializers.BooleanField()  # type: ignore[assignment]
    choices = serializers.ListField(child=serializers.CharField())
    default = serializers.CharField(allow_null=True)
    entity = serializers.CharField(allow_blank=True)


class ReportSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    title = serializers.CharField()
    group = serializers.ChoiceField(choices=GROUP_CHOICES)
    description = serializers.CharField(allow_blank=True)
    pdf = serializers.BooleanField(help_text="Also exported to PDF.")
    background_only = serializers.BooleanField(help_text="Always made in the background.")
    max_days = serializers.IntegerField(help_text="The longest date range.")
    own_shops = serializers.BooleanField(help_text="Rows only for the user's own shops.")
    columns = ColumnSerializer(many=True, help_text="Only the columns this user may see.")
    filters = FilterSerializer(many=True)


class ReportPageSerializer(serializers.Serializer[Any]):
    columns = ColumnSerializer(many=True)
    rows = serializers.ListField(
        child=serializers.DictField(),
        help_text="Keyed by column; money and quantities as strings; link ids such as "
        "retailer_id where a row links somewhere.",
    )
    totals = serializers.DictField(allow_null=True, help_text="For the whole report, not the page.")
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    own_shops = serializers.BooleanField()
    notes = serializers.ListField(child=serializers.CharField())


class ExportRequestSerializer(serializers.Serializer[Any]):
    format = serializers.ChoiceField(choices=ReportRun.Format.choices, default="XLSX")
    filters = serializers.DictField(required=False, default=dict)


class ReportRunSerializer(serializers.ModelSerializer[ReportRun]):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = ReportRun
        fields = [
            "id",
            "report_code",
            "title",
            "format",
            "status",
            "params",
            "row_count",
            "file_name",
            "error",
            "created_at",
            "finished_at",
            "expires_at",
            "download_url",
        ]
        read_only_fields = fields

    def get_download_url(self, run: ReportRun) -> str | None:
        from apps.reports.services import download_url

        return download_url(run)


# --- The distributor's dashboard (ADR-050 item 11) ----------------------------------------------


def _money_field(**kw: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=16, decimal_places=2, **kw)


class CountAmountSerializer(serializers.Serializer[Any]):
    count = serializers.IntegerField()
    amount = _money_field()


class ShopsAmountSerializer(serializers.Serializer[Any]):
    shops = serializers.IntegerField()
    amount = _money_field()


class LowStockCountsSerializer(serializers.Serializer[Any]):
    low = serializers.IntegerField()
    out = serializers.IntegerField()


class DashboardActionSerializer(serializers.Serializer[Any]):
    """What needs action today. A part is null for someone without its permission (or while
    its module is off)."""

    new_orders = serializers.IntegerField(allow_null=True)
    on_hold = serializers.IntegerField(allow_null=True)
    backorders_to_confirm = serializers.IntegerField(allow_null=True)
    to_pack = serializers.IntegerField(allow_null=True)
    failed_irns = serializers.IntegerField(allow_null=True)
    failed_ewaybills = serializers.IntegerField(allow_null=True)
    handover = CountAmountSerializer(allow_null=True, help_text="Collections not handed over.")
    overdue = ShopsAmountSerializer(allow_null=True, help_text="Overdue receivables.")
    low_stock = LowStockCountsSerializer(allow_null=True)
    to_reorder = serializers.IntegerField(
        allow_null=True, help_text="Open reorder suggestions (stock planning)."
    )
    late_purchase_orders = serializers.IntegerField(
        allow_null=True, help_text="Sent or partly received, expected before today (purchasing)."
    )
    win_back = serializers.IntegerField(
        allow_null=True,
        help_text="Shops to win back (ADR-056): slowing, stopped or never ordered, not contacted "
        "lately.",
    )
    return_requests = serializers.IntegerField(
        allow_null=True, help_text="Return requests from shops waiting for a decision (ADR-057)."
    )


class DashboardTodaySerializer(serializers.Serializer[Any]):
    orders_received = CountAmountSerializer(
        allow_null=True, help_text="Orders placed today (value incl. GST)."
    )
    billed = _money_field(allow_null=True, help_text="Invoices minus credit notes today.")


class TrendDaySerializer(serializers.Serializer[Any]):
    date = serializers.DateField()
    billed = _money_field()
    previous = _money_field(help_text="Billed on the same day of the 30 days before.")


class TopProductSerializer(serializers.Serializer[Any]):
    product_id = serializers.UUIDField()
    name = serializers.CharField()
    total = _money_field()


class TopShopSerializer(serializers.Serializer[Any]):
    retailer_id = serializers.UUIDField()
    name = serializers.CharField()
    total = _money_field()


class DashboardTrendsSerializer(serializers.Serializer[Any]):
    days = TrendDaySerializer(many=True)
    billed_30_days = _money_field()
    billed_previous_30_days = _money_field()
    top_products = TopProductSerializer(many=True, help_text="This month, by net sales.")
    top_shops = TopShopSerializer(many=True, help_text="This month, by net sales.")
    new_shops = serializers.IntegerField(help_text="Ordered this month for the first time.")
    repeat_shops = serializers.IntegerField()


class DistributorDashboardSerializer(serializers.Serializer[Any]):
    action = DashboardActionSerializer()
    today = DashboardTodaySerializer()
    trends = DashboardTrendsSerializer(allow_null=True, help_text="With the sales reports.")
    own_shops = serializers.BooleanField(help_text="Figures only for the user's own shops.")
