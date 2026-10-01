"""Stock planning (ADR-053, flag ``stock_planning``): each product's demand and classes, worked out
nightly and on demand. Reorder suggestions build on these figures."""

from django.db import models
from django.db.models import Q

from common.fields import MoneyField, QtyField
from common.models import TenantScopedModel


class AbcClass(models.TextChoices):
    A = "A", "A"
    B = "B", "B"
    C = "C", "C"


class MovementClass(models.TextChoices):
    FAST = "FAST", "Fast"
    SLOW = "SLOW", "Slow"
    DEAD = "DEAD", "Dead"
    NEW = "NEW", "New"


class ProductStats(TenantScopedModel):
    """One row per product, replaced each time the figures are worked out. The settings used are
    kept with them, so the app can say what they cover."""

    product = models.OneToOneField(
        "catalog.Product", on_delete=models.CASCADE, related_name="stats"
    )
    computed_at = models.DateTimeField()
    # Demand: quantity ordered (base unit) in the last ``demand_days`` days, the shop's own
    # cancellations and rejected orders left out.
    demand_days = models.PositiveSmallIntegerField()
    demand_qty = QtyField(default=0)
    per_day = QtyField(default=0)
    # Sales value (taxable, net of credit notes) over ⚙ reports.movement_days, for the classes.
    movement_days = models.PositiveSmallIntegerField()
    sold_value = MoneyField(default=0)
    abc_class = models.CharField(max_length=1, choices=AbcClass.choices, null=True, blank=True)  # noqa: DJ001
    movement_class = models.CharField(  # noqa: DJ001
        max_length=4, choices=MovementClass.choices, null=True, blank=True
    )
    last_sale_date = models.DateField(null=True, blank=True)
    available = QtyField(default=0)  # on hand less reserved, when worked out
    days_of_stock = models.DecimalField(max_digits=9, decimal_places=1, null=True, blank=True)

    class Meta:
        verbose_name_plural = "product stats"
        indexes = [
            models.Index(
                fields=["tenant", "abc_class"],
                condition=Q(abc_class__isnull=False),
                name="stats_abc_idx",
            ),
            models.Index(
                fields=["tenant", "movement_class"],
                condition=Q(movement_class__isnull=False),
                name="stats_movement_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(demand_qty__gte=0) & Q(per_day__gte=0), name="stats_demand_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"stats {self.product_id}"
