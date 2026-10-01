"""Stock planning (ADR-053, flag ``stock_planning``): each product's demand and classes, worked out
nightly and on demand. Reorder suggestions build on these figures."""

from typing import Any

from django.conf import settings
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


class ReorderSuggestion(TenantScopedModel):
    """What to order of a product and why (ADR-053 item 8). One open suggestion per product,
    worked out with the stats; the figures are kept so the app can explain it in plain words."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        ORDERED = "ORDERED", "Ordered"  # put on a purchase order
        DISMISSED = "DISMISSED", "Dismissed"  # not suggested again until ``dismissed_until``
        RESOLVED = "RESOLVED", "No longer needed"
        # Below its reorder level but not selling, no shop waiting: shown apart, never ordered
        # (final review): the reorder level may be too high.
        NOT_SELLING = "NOT_SELLING", "Below its reorder level, not selling"

    class Basis(models.TextChoices):
        DEMAND = "DEMAND", "Daily demand"
        LOW_HISTORY = "LOW_HISTORY", "Little or no sales history"

    class LeadSource(models.TextChoices):
        PRODUCT_SUPPLIER = "PRODUCT_SUPPLIER", "The supplier's time for this product"
        SUPPLIER = "SUPPLIER", "The supplier's usual time"
        DEFAULT = "DEFAULT", "Your usual delivery time"

    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="reorder_suggestions"
    )
    supplier = models.ForeignKey(
        "purchasing.Supplier", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    status = models.CharField(max_length=11, choices=Status.choices, default=Status.OPEN)
    computed_at = models.DateTimeField()
    basis = models.CharField(max_length=11, choices=Basis.choices)
    demand_qty = QtyField(default=0)
    demand_days = models.PositiveSmallIntegerField()
    per_day = QtyField(default=0)
    available = QtyField(default=0)  # on hand less reserved
    on_order = QtyField(default=0)  # still due on sent purchase orders
    waiting = QtyField(default=0)  # shops' backorders
    reorder_level = QtyField(default=0)  # the product's own level, for little history
    lead_days = models.PositiveSmallIntegerField()
    lead_source = models.CharField(max_length=16, choices=LeadSource.choices)
    safety_days = models.PositiveSmallIntegerField()
    cover_days = models.PositiveSmallIntegerField()
    reorder_point = QtyField(default=0)
    pack_size = QtyField(null=True, blank=True)  # the supplier's pack the quantity rounds up to
    suggested_qty = QtyField()
    quantity = QtyField(null=True, blank=True)  # changed by staff; null = the suggestion
    days_left = models.DecimalField(max_digits=9, decimal_places=1, null=True, blank=True)
    last_sale_date = models.DateField(null=True, blank=True)  # none: never sold
    purchase_order_line = models.ForeignKey(
        "purchasing.PurchaseOrderLine",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    dismissed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    dismissed_at = models.DateTimeField(null=True, blank=True)
    dismissed_until = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "product"],
                condition=Q(status="OPEN"),
                name="uniq_open_suggestion",
            ),
            models.CheckConstraint(
                condition=Q(suggested_qty__gt=0) & (Q(quantity__isnull=True) | Q(quantity__gt=0)),
                name="suggestion_quantities",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "status"], name="suggestion_status_idx")]

    @property
    def to_order(self) -> Any:
        return self.quantity if self.quantity is not None else self.suggested_qty

    def __str__(self) -> str:
        return f"suggest {self.product_id} {self.status}"
