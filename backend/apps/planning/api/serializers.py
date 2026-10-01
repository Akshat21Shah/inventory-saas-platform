from rest_framework import serializers

from apps.planning.models import AbcClass, MovementClass, ProductStats


class ProductStatsSerializer(serializers.ModelSerializer[ProductStats]):
    """A product's demand and classes. No money: the classes come from sales value, which sales
    staff limited to their own shops may not see."""

    abc_class = serializers.ChoiceField(choices=AbcClass.choices, allow_null=True)
    movement_class = serializers.ChoiceField(choices=MovementClass.choices, allow_null=True)

    class Meta:
        model = ProductStats
        fields = [
            "computed_at",
            "demand_days",
            "demand_qty",
            "per_day",
            "movement_days",
            "abc_class",
            "movement_class",
            "last_sale_date",
            "available",
            "days_of_stock",
        ]
        read_only_fields = fields


class PlanningRefreshSerializer(serializers.Serializer[object]):
    status = serializers.ChoiceField(choices=["QUEUED"])
