from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.planning.models import AbcClass, MovementClass, ProductStats, ReorderSuggestion
from apps.planning.quantities import RatePeriod, demand_rate


class DemandRateSerializer(serializers.Serializer[object]):
    """What shops order, as "about {quantity} a {period}": per day from 1 a day, else per week,
    else per month. 0 a month: less than 1 a month (units that can't be split)."""

    quantity = serializers.DecimalField(max_digits=14, decimal_places=2)
    period = serializers.ChoiceField(choices=RatePeriod.choices)


def _rate(demand_qty: Any, demand_days: int, product: Any) -> dict[str, Any]:
    quantity, period = demand_rate(demand_qty, demand_days, not product.unit.allows_decimal)
    return dict(DemandRateSerializer({"quantity": quantity, "period": period}).data)


class ProductStatsSerializer(serializers.ModelSerializer[ProductStats]):
    """A product's demand and classes. No money: the classes come from sales value, which sales
    staff limited to their own shops may not see."""

    abc_class = serializers.ChoiceField(choices=AbcClass.choices, allow_null=True)
    movement_class = serializers.ChoiceField(choices=MovementClass.choices, allow_null=True)
    demand_rate = serializers.SerializerMethodField()

    class Meta:
        model = ProductStats
        fields = [
            "computed_at",
            "demand_days",
            "demand_qty",
            "per_day",
            "demand_rate",
            "movement_days",
            "abc_class",
            "movement_class",
            "last_sale_date",
            "available",
            "days_of_stock",
        ]
        read_only_fields = fields

    @extend_schema_field(DemandRateSerializer)
    def get_demand_rate(self, stats: ProductStats) -> dict[str, Any]:
        return _rate(stats.demand_qty, stats.demand_days, stats.product)


class PlanningRefreshSerializer(serializers.Serializer[object]):
    status = serializers.ChoiceField(choices=["QUEUED"])


class SuggestionFilterSerializer(serializers.Serializer[object]):
    supplier = serializers.UUIDField(required=False, allow_null=True, default=None)
    basis = serializers.ChoiceField(
        choices=ReorderSuggestion.Basis.choices, required=False, allow_blank=True, default=""
    )
    search = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)


class ReorderSuggestionSerializer(serializers.ModelSerializer[ReorderSuggestion]):
    """The figures behind a suggestion, for the app to explain it in plain words. The supplier is
    named only to staff who can see purchasing (``context["suppliers"]``); no money."""

    product_id = serializers.UUIDField(read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    unit_code = serializers.CharField(source="product.unit.code", read_only=True)
    supplier_id = serializers.UUIDField(read_only=True, allow_null=True)
    supplier_name = serializers.SerializerMethodField()
    to_order = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    demand_rate = serializers.SerializerMethodField()

    class Meta:
        model = ReorderSuggestion
        fields = [
            "id",
            "product_id",
            "product_code",
            "product_name",
            "unit_code",
            "supplier_id",
            "supplier_name",
            "basis",
            "computed_at",
            "demand_qty",
            "demand_days",
            "per_day",
            "demand_rate",
            "available",
            "on_order",
            "waiting",
            "reorder_level",
            "lead_days",
            "lead_source",
            "safety_days",
            "cover_days",
            "reorder_point",
            "pack_size",
            "suggested_qty",
            "quantity",
            "to_order",
            "days_left",
        ]
        read_only_fields = fields

    @extend_schema_field(DemandRateSerializer)
    def get_demand_rate(self, row: ReorderSuggestion) -> dict[str, Any]:
        return _rate(row.demand_qty, row.demand_days, row.product)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_supplier_name(self, row: ReorderSuggestion) -> str | None:
        if not self.context.get("suppliers") or row.supplier is None:
            return None
        return row.supplier.name

    def to_representation(self, instance: ReorderSuggestion) -> dict[str, Any]:
        data = super().to_representation(instance)
        if not self.context.get("suppliers"):
            data["supplier_id"] = None
        return data


class SuggestionChangeSerializer(serializers.Serializer[object]):
    quantity = serializers.DecimalField(
        max_digits=14, decimal_places=3, required=False, allow_null=True
    )
    dismiss = serializers.BooleanField(required=False, default=False)
    until = serializers.DateField(required=False, allow_null=True, default=None)


class SuggestionIdsSerializer(serializers.Serializer[object]):
    suggestion_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=500
    )


class CreatedOrderSerializer(serializers.Serializer[object]):
    id = serializers.UUIDField()
    number = serializers.CharField()
    supplier_name = serializers.CharField()
    line_count = serializers.IntegerField()


class LevelsAppliedSerializer(serializers.Serializer[object]):
    changed = serializers.IntegerField()
