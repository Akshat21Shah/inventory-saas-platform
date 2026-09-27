"""Orders (PLAN §2.8, spec 5.8 and 5.9, ADR-006/013/014/044): carts, orders with price and settings
snapshots, status history, shipments (fulfilments) and backorder allocations. All write logic lives
in ``services.py``; quantities are in the product's base unit."""

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from common.fields import MoneyField, QtyField, RateField
from common.models import TenantScopedModel

USER = settings.AUTH_USER_MODEL


class Cart(TenantScopedModel):
    """One per (shop, user): the shop's login, or a staff member ordering on its behalf, so they
    never change each other's cart (ADR-044)."""

    retailer = models.ForeignKey("retailers.Retailer", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["retailer", "user"], name="uniq_cart_per_user")
        ]

    def __str__(self) -> str:
        return f"cart {self.retailer_id}/{self.user_id}"


class CartLine(TenantScopedModel):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="+")
    quantity = QtyField()

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["cart", "product"], name="uniq_cart_product"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="cart_line_qty_pos"),
        ]

    def __str__(self) -> str:
        return f"{self.product_id} x {self.quantity}"


class OrderStatus(models.TextChoices):
    PLACED = "PLACED", "Placed"
    ON_HOLD = "ON_HOLD", "On hold"
    ACCEPTED = "ACCEPTED", "Accepted"
    PACKED = "PACKED", "Packed"
    DISPATCHED = "DISPATCHED", "Dispatched"
    DELIVERED = "DELIVERED", "Delivered"
    COMPLETED = "COMPLETED", "Completed"
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"


OPEN_STATUSES = (
    OrderStatus.PLACED,
    OrderStatus.ON_HOLD,
    OrderStatus.ACCEPTED,
    OrderStatus.PACKED,
    OrderStatus.DISPATCHED,
    OrderStatus.DELIVERED,
)
ACCEPTED_STATUSES = (
    OrderStatus.ACCEPTED,
    OrderStatus.PACKED,
    OrderStatus.DISPATCHED,
    OrderStatus.DELIVERED,
)


class Order(TenantScopedModel):
    class PlacedVia(models.TextChoices):
        RETAILER_APP = "RETAILER_APP", "Shop app"
        STAFF = "STAFF", "Staff"

    class BackorderState(models.TextChoices):
        NONE = "NONE", "None"
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    class HoldReason(models.TextChoices):
        CREDIT_LIMIT = "CREDIT_LIMIT", "Over the credit limit"
        OVERDUE = "OVERDUE", "Overdue invoices"

    number = models.CharField(max_length=24)  # ORD-2026-000123
    retailer = models.ForeignKey(
        "retailers.Retailer", on_delete=models.PROTECT, related_name="orders"
    )
    placed_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    placed_via = models.CharField(max_length=14, choices=PlacedVia.choices)
    # "Priya (Sales)" when staff placed it for the shop (ADR-044); empty when the shop did.
    placed_by_label = models.CharField(max_length=160, blank=True, default="")
    status = models.CharField(max_length=12, choices=OrderStatus.choices)
    backorder_state = models.CharField(
        max_length=6, choices=BackorderState.choices, default=BackorderState.NONE
    )
    hold_reason = models.CharField(
        max_length=14, choices=HoldReason.choices, blank=True, default=""
    )
    # Settings in effect when placed (registry keys snapshotted on ORDER, ADR-016).
    settings_snapshot = models.JSONField(default=dict)
    shipping_address = models.JSONField(default=dict)
    billing_address = models.JSONField(default=dict)
    place_of_supply = models.ForeignKey(
        "platform.State", on_delete=models.PROTECT, related_name="+"
    )
    supply_type = models.CharField(max_length=5)  # INTRA / INTER
    prices_include_tax = models.BooleanField(default=False)
    # Estimates (the invoice is final, Phase 5).
    gross_total = MoneyField(default=0)
    discount_total = MoneyField(default=0)
    taxable_total = MoneyField(default=0)
    tax_total = MoneyField(default=0)
    round_off = MoneyField(default=0)
    grand_total = MoneyField(default=0)
    retailer_note = models.CharField(
        max_length=500, blank=True, default=""
    )  # delivery instructions
    internal_note = models.TextField(blank=True, default="")
    placed_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=500, blank=True, default="")
    cancellation_reason = models.CharField(max_length=500, blank=True, default="")
    cancelled_by = models.ForeignKey(
        USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-placed_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="uniq_order_number"),
            models.CheckConstraint(
                condition=Q(gross_total__gte=0)
                & Q(discount_total__gte=0)
                & Q(taxable_total__gte=0)
                & Q(tax_total__gte=0)
                & Q(grand_total__gte=0),
                name="order_totals_nonneg",
            ),
        ]
        indexes = [
            models.Index("tenant", "status", F("placed_at").desc(), name="order_status_idx"),
            models.Index("tenant", "retailer", F("placed_at").desc(), name="order_retailer_idx"),
            models.Index(fields=["tenant", "backorder_state"], name="order_backorder_idx"),
        ]

    def __str__(self) -> str:
        return self.number


class OrderLine(TenantScopedModel):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    # Snapshot of the product and its price when ordered.
    product_code = models.CharField(max_length=40)
    product_name = models.CharField(max_length=200)
    hsn_code = models.CharField(max_length=8)
    unit_code = models.CharField(max_length=10)
    base_price = MoneyField()
    unit_price = MoneyField()
    price_source = models.CharField(max_length=12)  # SPECIAL, PRICE_LIST, BASE
    discount_per_unit = MoneyField(default=0)  # informational (what the shop sees)
    gst_rate = RateField()
    cess_rate = RateField(default=0)
    # Quantity buckets: ordered = pending + reserved + backordered + allocated + cancelled.
    qty_ordered = QtyField()
    qty_pending = QtyField(default=0)  # on credit hold without reserving stock
    qty_reserved = QtyField(default=0)  # held, not yet in a shipment
    qty_backordered = QtyField(default=0)  # waiting for stock
    qty_allocated = QtyField(default=0)  # moved into shipments
    qty_cancelled = QtyField(default=0)
    qty_dispatched = QtyField(default=0)
    qty_delivered = QtyField(default=0)
    # Estimates for the ordered quantity, on the order's price basis (incl. GST when prices
    # include it). The order's totals are recomputed from these for what stays open.
    gross_amount = MoneyField(default=0)
    discount_amount = MoneyField(default=0)
    taxable_amount = MoneyField(default=0)
    tax_amount = MoneyField(default=0)
    line_total = MoneyField(default=0)

    class Meta:
        ordering = ["line_no"]
        constraints = [
            models.UniqueConstraint(fields=["order", "line_no"], name="uniq_order_line_no"),
            models.CheckConstraint(
                condition=Q(
                    qty_ordered=F("qty_pending")
                    + F("qty_reserved")
                    + F("qty_backordered")
                    + F("qty_allocated")
                    + F("qty_cancelled")
                ),
                name="order_line_qty_buckets",
            ),
            models.CheckConstraint(
                condition=Q(qty_ordered__gt=0)
                & Q(qty_pending__gte=0)
                & Q(qty_reserved__gte=0)
                & Q(qty_backordered__gte=0)
                & Q(qty_allocated__gte=0)
                & Q(qty_cancelled__gte=0)
                & Q(qty_dispatched__gte=0)
                & Q(qty_delivered__gte=0),
                name="order_line_qty_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(qty_dispatched__lte=F("qty_allocated"))
                & Q(qty_delivered__lte=F("qty_dispatched")),
                name="order_line_shipped_within_allocated",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "product", "created_at"],
                condition=Q(qty_backordered__gt=0),
                name="order_line_backorder_queue",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.order_id}#{self.line_no}"


class OrderLineDiscount(TenantScopedModel):
    """Every discount rule applied to the line, in the order applied (ADR-038 item 3)."""

    order_line = models.ForeignKey(OrderLine, on_delete=models.CASCADE, related_name="discounts")
    position = models.PositiveSmallIntegerField()
    rule = models.ForeignKey(
        "pricing.DiscountRule", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    rule_name = models.CharField(max_length=120)
    discount_type = models.CharField(max_length=16)
    value = MoneyField()
    amount = MoneyField()

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["order_line", "position"], name="uniq_order_line_discount"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.rule_name}: {self.amount}"


class OrderEvent(models.TextChoices):
    PLACE = "PLACE", "Placed"
    HOLD = "HOLD", "Put on hold"
    APPROVE_HOLD = "APPROVE_HOLD", "Hold approved"
    ACCEPT = "ACCEPT", "Accepted"
    REJECT = "REJECT", "Rejected"
    CANCEL = "CANCEL", "Cancelled"
    MODIFY = "MODIFY", "Changed"
    PACK = "PACK", "Packed"
    DISPATCH = "DISPATCH", "Dispatched"
    DELIVER = "DELIVER", "Delivered"
    SHORT_SUPPLY = "SHORT_SUPPLY", "Short supplied"
    BACKORDER_ALLOCATED = "BACKORDER_ALLOCATED", "Backorder allocated"
    BACKORDER_CANCELLED = "BACKORDER_CANCELLED", "Backorder cancelled"
    COMPLETE = "COMPLETE", "Completed"


class OrderStatusHistory(TenantScopedModel):
    """Append-only timeline (database trigger)."""

    class ActorType(models.TextChoices):
        RETAILER = "RETAILER", "Shop"
        STAFF = "STAFF", "Staff"
        SYSTEM = "SYSTEM", "System"

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="history")
    from_status = models.CharField(max_length=12, blank=True, default="")
    to_status = models.CharField(max_length=12)
    event = models.CharField(max_length=20, choices=OrderEvent.choices)
    actor = models.ForeignKey(
        USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    actor_type = models.CharField(max_length=8, choices=ActorType.choices)
    note = models.CharField(max_length=500, blank=True, default="")
    payload = models.JSONField(default=dict)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["tenant", "order", "created_at"], name="order_history_idx")]

    def __str__(self) -> str:
        return f"{self.order_id} {self.event}"


class Fulfilment(TenantScopedModel):
    """A shipment: the initial one, or one per backorder allocation (ADR-006)."""

    class Kind(models.TextChoices):
        INITIAL = "INITIAL", "First shipment"
        BACKORDER = "BACKORDER", "Backorder shipment"

    class Status(models.TextChoices):
        ALLOCATED = "ALLOCATED", "To pack"
        PACKED = "PACKED", "Packed"
        DISPATCHED = "DISPATCHED", "Dispatched"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="fulfilments")
    number = models.CharField(max_length=28)  # ORD-2026-000123/2
    kind = models.CharField(max_length=10, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ALLOCATED)
    warehouse = models.ForeignKey("inventory.Warehouse", on_delete=models.PROTECT, related_name="+")
    vehicle_number = models.CharField(max_length=20, blank=True, default="")
    transporter_name = models.CharField(max_length=120, blank=True, default="")
    lr_number = models.CharField(max_length=40, blank=True, default="")
    packed_at = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancelled_reason = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="uniq_fulfilment_number"),
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "created_at"], name="fulfilment_status_idx")
        ]

    def __str__(self) -> str:
        return self.number


class FulfilmentLine(TenantScopedModel):
    class PriceSource(models.TextChoices):
        ORDER_SNAPSHOT = "ORDER_SNAPSHOT", "Order price"
        REPRICED = "REPRICED", "Today's price"

    fulfilment = models.ForeignKey(Fulfilment, on_delete=models.PROTECT, related_name="lines")
    order_line = models.ForeignKey(OrderLine, on_delete=models.PROTECT, related_name="+")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    quantity = QtyField()
    qty_packed = QtyField(null=True, blank=True)
    unit_price = MoneyField()
    price_source = models.CharField(
        max_length=14, choices=PriceSource.choices, default=PriceSource.ORDER_SNAPSHOT
    )
    price_increased = models.BooleanField(default=False)
    cancelled_by_retailer_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["fulfilment", "order_line"], name="uniq_fulfilment_line"
            ),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="fulfilment_line_qty_pos"),
            models.CheckConstraint(
                condition=Q(qty_packed__isnull=True)
                | (Q(qty_packed__gte=0) & Q(qty_packed__lte=F("quantity"))),
                name="fulfilment_line_packed_within",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.fulfilment_id}:{self.order_line_id} x {self.quantity}"


class BackorderAllocation(TenantScopedModel):
    class Status(models.TextChoices):
        PROPOSED = "PROPOSED", "Proposed"
        CONFIRMED = "CONFIRMED", "Confirmed"
        REJECTED = "REJECTED", "Rejected"
        SKIPPED_CREDIT = "SKIPPED_CREDIT", "Skipped: over credit limit"

    class Trigger(models.TextChoices):
        INWARD = "INWARD", "Goods received"
        ADJUSTMENT_IN = "ADJUSTMENT_IN", "Stock added"
        RELEASE = "RELEASE", "Stock released"
        MANUAL = "MANUAL", "Manual"

    order_line = models.ForeignKey(OrderLine, on_delete=models.PROTECT, related_name="allocations")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    warehouse = models.ForeignKey("inventory.Warehouse", on_delete=models.PROTECT, related_name="+")
    quantity = QtyField()
    status = models.CharField(max_length=15, choices=Status.choices)
    trigger = models.CharField(max_length=14, choices=Trigger.choices)
    source_id = models.UUIDField(null=True, blank=True)
    fulfilment = models.ForeignKey(
        Fulfilment, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    decided_by = models.ForeignKey(
        USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="allocation_qty_pos"),
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "created_at"], name="allocation_status_idx"),
            models.Index(fields=["tenant", "order_line"], name="allocation_line_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.order_line_id} {self.quantity} {self.status}"
