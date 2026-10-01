"""Inventory (PLAN §2.7, spec 5.7, ADR-041): warehouses, stock levels, the append-only movement
log, goods receipts, adjustments and alerts. Every stock change goes through ``services.py``."""

from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.indexes import BrinIndex
from django.db import models
from django.db.models import F, Q

from common.fields import MoneyField, QtyField, UnitCostField
from common.models import TenantScopedModel


class Warehouse(TenantScopedModel):
    """One default warehouse per tenant; more behind the ``multi_warehouse`` flag later."""

    code = models.CharField(max_length=20)
    name = models.CharField(max_length=120)
    address_line1 = models.CharField(max_length=200, blank=True, default="")
    address_line2 = models.CharField(max_length=200, blank=True, default="")
    city = models.CharField(max_length=80, blank=True, default="")
    pincode = models.CharField(max_length=6, blank=True, default="")
    state = models.ForeignKey(
        "platform.State", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_default", "name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_warehouse_code"),
            models.UniqueConstraint(
                fields=["tenant"], condition=Q(is_default=True), name="uniq_default_warehouse"
            ),
        ]

    def __str__(self) -> str:
        return self.code


class StockLevel(TenantScopedModel):
    """Quantities in the product's base unit. Changed only by ``services._apply_movement``."""

    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="+")
    quantity_on_hand = QtyField(default=0)
    quantity_reserved = QtyField(default=0)
    # Open backorder demand, kept in step by the order services (Phase 4).
    quantity_backordered = QtyField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["product", "warehouse"], name="uniq_stock_level"),
            models.CheckConstraint(
                condition=Q(quantity_on_hand__gte=0), name="stock_on_hand_nonneg"
            ),
            models.CheckConstraint(
                condition=Q(quantity_reserved__gte=0), name="stock_reserved_nonneg"
            ),
            models.CheckConstraint(
                condition=Q(quantity_backordered__gte=0), name="stock_backordered_nonneg"
            ),
            models.CheckConstraint(
                condition=Q(quantity_reserved__lte=F("quantity_on_hand")),
                name="stock_reserved_within_on_hand",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "warehouse", "product"], name="stock_level_wh_idx")
        ]

    def __str__(self) -> str:
        return f"{self.product_id}@{self.warehouse_id}: {self.quantity_on_hand}"

    @property
    def available(self) -> Decimal:
        return Decimal(self.quantity_on_hand) - Decimal(self.quantity_reserved)


class MovementType(models.TextChoices):
    """What happened. Each type's direction lives in ``services.MOVEMENT_KINDS``; there is no
    database list of types, so manufacturing can add CONSUME / PRODUCE later (ADR-041)."""

    INWARD = "INWARD", "Goods received"
    SALE = "SALE", "Dispatched"
    RETURN = "RETURN", "Returned"
    ADJUSTMENT_IN = "ADJUSTMENT_IN", "Adjustment in"
    ADJUSTMENT_OUT = "ADJUSTMENT_OUT", "Adjustment out"
    DAMAGE = "DAMAGE", "Damaged"
    TRANSFER_IN = "TRANSFER_IN", "Transfer in"
    TRANSFER_OUT = "TRANSFER_OUT", "Transfer out"
    RESERVE = "RESERVE", "Reserved for an order"
    RELEASE = "RELEASE", "Reservation released"


class ReferenceType(models.TextChoices):
    INWARD = "INWARD", "Goods receipt"
    ADJUSTMENT = "ADJUSTMENT", "Adjustment"
    ORDER = "ORDER", "Order"
    ORDER_LINE = "ORDER_LINE", "Order line"
    FULFILMENT = "FULFILMENT", "Shipment"
    CREDIT_NOTE = "CREDIT_NOTE", "Credit note"
    ALLOCATION = "ALLOCATION", "Backorder allocation"


class StockMovement(TenantScopedModel):
    """Append-only (database trigger). Corrections are new movements, never edits."""

    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="+")
    movement_type = models.CharField(max_length=30, choices=MovementType.choices)
    quantity = QtyField()
    delta_on_hand = QtyField()
    delta_reserved = QtyField()
    on_hand_after = QtyField()
    reserved_after = QtyField()
    unit_cost = UnitCostField(null=True, blank=True)  # per base unit, before GST
    value = MoneyField(null=True, blank=True)  # quantity x unit_cost, to the paisa
    reference_type = models.CharField(max_length=30, choices=ReferenceType.choices)
    reference_id = models.UUIDField()
    reference_number = models.CharField(max_length=40, blank=True, default="")
    reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="movement_qty_pos"),
            models.CheckConstraint(
                condition=Q(on_hand_after__gte=0) & Q(reserved_after__gte=0),
                name="movement_balances_nonneg",
            ),
        ]
        indexes = [
            models.Index("tenant", "product", F("created_at").desc(), name="movement_product_idx"),
            models.Index(
                fields=["tenant", "reference_type", "reference_id"], name="movement_ref_idx"
            ),
            models.Index(
                fields=["tenant", "movement_type", "created_at"], name="movement_type_idx"
            ),
            BrinIndex(fields=["created_at"], name="movement_created_brin"),
        ]

    def __str__(self) -> str:
        return f"{self.movement_type} {self.quantity} of {self.product_id}"


class StockInward(TenantScopedModel):
    """A goods receipt (GRN). DRAFT → POSTED; a posted receipt only gains missing costs."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        POSTED = "POSTED", "Posted"

    # GRN-2026-00012, given when posted; NULL (not "") so drafts don't collide on the unique key.
    number = models.CharField(max_length=24, null=True, blank=True)  # noqa: DJ001
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="+")
    supplier_name = models.CharField(max_length=200, blank=True, default="")  # as typed
    # The supplier (ADR-053, flag purchasing): chosen on new receipts, or linked once to a past
    # one through the review of typed names; never changed after that.
    supplier = models.ForeignKey(
        "purchasing.Supplier",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="receipts",
    )
    supplier_ref = models.CharField(max_length=60, blank=True, default="")
    bill_number = models.CharField(max_length=60, blank=True, default="")
    bill_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    notes = models.TextField(blank=True, default="")
    total_cost = MoneyField(null=True, blank=True)  # lines that have a cost
    cost_pending_lines = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="uniq_inward_number"),
            models.CheckConstraint(
                condition=Q(status="DRAFT")
                | (Q(number__isnull=False) & Q(posted_at__isnull=False)),
                name="inward_posted_complete",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "created_at"], name="inward_status_idx"),
            models.Index(
                fields=["tenant"], condition=Q(cost_pending_lines__gt=0), name="inward_cost_pending"
            ),
        ]

    def __str__(self) -> str:
        return self.number or f"draft {self.pk}"


class StockInwardLine(TenantScopedModel):
    class EnteredUnit(models.TextChoices):
        BASE = "BASE", "Base unit"
        PACK = "PACK", "Pack"

    class CostStatus(models.TextChoices):
        SET = "SET", "Cost entered"
        PENDING = "PENDING", "Cost pending"

    inward = models.ForeignKey(StockInward, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    entered_unit = models.CharField(
        max_length=4, choices=EnteredUnit.choices, default=EnteredUnit.BASE
    )
    entered_qty = QtyField()
    quantity = QtyField()  # base unit
    # Cost of one entered unit (a pack or a base unit) as on the bill, before GST (ADR-041).
    entered_cost = UnitCostField(null=True, blank=True)
    unit_cost = UnitCostField(null=True, blank=True)  # per base unit, derived from entered_cost
    line_cost = MoneyField(null=True, blank=True)
    # NULL while the receipt is a draft; SET or PENDING once posted.
    cost_status = models.CharField(  # noqa: DJ001
        max_length=8, choices=CostStatus.choices, null=True, blank=True
    )
    cost_completed_at = models.DateTimeField(null=True, blank=True)
    cost_completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["line_no"]
        constraints = [
            models.UniqueConstraint(fields=["inward", "line_no"], name="uniq_inward_line_no"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="inward_line_qty_pos"),
            models.CheckConstraint(condition=Q(entered_qty__gt=0), name="inward_line_entered_pos"),
            models.CheckConstraint(
                condition=Q(unit_cost__isnull=True) | Q(unit_cost__gte=0),
                name="inward_line_cost_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(entered_cost__isnull=True, unit_cost__isnull=True)
                | Q(entered_cost__gte=0, unit_cost__isnull=False),
                name="inward_line_cost_pair",
            ),
            models.CheckConstraint(
                condition=Q(cost_status__isnull=True)
                | (Q(cost_status="SET") & Q(unit_cost__isnull=False))
                | (Q(cost_status="PENDING") & Q(unit_cost__isnull=True)),
                name="inward_line_cost_status",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "product"], name="inward_line_product_idx")]

    def __str__(self) -> str:
        return f"{self.inward_id}#{self.line_no}"


class AdjustmentReason(models.TextChoices):
    COUNT_CORRECTION = "COUNT_CORRECTION", "Stock count correction"
    DAMAGE = "DAMAGE", "Damaged"
    EXPIRY = "EXPIRY", "Expired"
    THEFT = "THEFT", "Lost or stolen"
    OPENING_STOCK = "OPENING_STOCK", "Opening stock"
    OTHER = "OTHER", "Other"


class StockAdjustment(TenantScopedModel):
    """Immutable after creation (append-only trigger); audited."""

    number = models.CharField(max_length=24)  # ADJ-2026-00012
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="+")
    reason_code = models.CharField(max_length=20, choices=AdjustmentReason.choices)
    note = models.TextField()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="uniq_adjustment_number"),
            models.CheckConstraint(condition=~Q(note=""), name="adjustment_note_required"),
        ]
        indexes = [models.Index(fields=["tenant", "created_at"], name="adjustment_created_idx")]

    def __str__(self) -> str:
        return self.number


class StockAdjustmentLine(TenantScopedModel):
    class Mode(models.TextChoices):
        ADD = "ADD", "Add"
        REMOVE = "REMOVE", "Remove"
        COUNTED = "COUNTED", "Counted"

    adjustment = models.ForeignKey(StockAdjustment, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    mode = models.CharField(max_length=8, choices=Mode.choices)
    entered_qty = QtyField()  # the counted quantity for COUNTED
    quantity_change = QtyField()  # signed, base unit
    on_hand_before = QtyField()

    class Meta:
        ordering = ["line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["adjustment", "line_no"], name="uniq_adjustment_line_no"
            ),
            models.CheckConstraint(
                condition=~Q(quantity_change=0), name="adjustment_line_change_nonzero"
            ),
            models.CheckConstraint(
                condition=Q(entered_qty__gt=0) | (Q(mode="COUNTED") & Q(entered_qty=0)),
                name="adjustment_line_entered",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "product"], name="adjustment_line_product_idx")]

    def __str__(self) -> str:
        return f"{self.adjustment_id}#{self.line_no}"


class StockAlert(TenantScopedModel):
    class Type(models.TextChoices):
        LOW_STOCK = "LOW_STOCK", "Low stock"
        OUT_OF_STOCK = "OUT_OF_STOCK", "Out of stock"
        BACKORDER_DEMAND = "BACKORDER_DEMAND", "Shops waiting"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        RESOLVED = "RESOLVED", "Resolved"

    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="+")
    alert_type = models.CharField(max_length=20, choices=Type.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    opened_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    value_at_open = QtyField()

    class Meta:
        ordering = ["-opened_at"]
        constraints = [
            # One open alert per product, warehouse and type: an alert fires once (PLAN §5.4).
            models.UniqueConstraint(
                fields=["tenant", "product", "warehouse", "alert_type"],
                condition=Q(status="OPEN"),
                name="uniq_open_stock_alert",
            ),
            models.CheckConstraint(
                condition=Q(status="OPEN", resolved_at__isnull=True)
                | Q(status="RESOLVED", resolved_at__isnull=False),
                name="stock_alert_resolved_at",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "alert_type"], name="stock_alert_status_idx")
        ]

    def __str__(self) -> str:
        return f"{self.alert_type} {self.product_id} ({self.status})"
