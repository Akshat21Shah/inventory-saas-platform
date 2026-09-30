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
