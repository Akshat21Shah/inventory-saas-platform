"""Suppliers and what they supply (ADR-053 items 4 to 6, flag ``purchasing``). Purchasing never
touches the shops' ledger; stock still changes only through goods receipts."""

from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import F, Q

from apps.billing.models import PdfStatus
from common.fields import MoneyField, QtyField, RateField, UnitCostField
from common.models import SoftDeleteMixin, TenantScopedModel
from common.search_keys import SearchKey


class Supplier(SoftDeleteMixin, TenantScopedModel):
    code = models.CharField(max_length=20)  # S-0001, allocated per tenant
    name = models.CharField(max_length=200)
    # In English letters, for search in either script (ADR-060 item 8). Kept by the database.
    name_key = models.GeneratedField(
        expression=SearchKey("name"), output_field=models.TextField(), db_persist=True
    )
    gstin = models.CharField(max_length=15, null=True, blank=True)  # noqa: DJ001
    state = models.ForeignKey(
        "platform.State", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    contact_name = models.CharField(max_length=150, blank=True, default="")
    phone = models.CharField(max_length=16, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    address_line1 = models.CharField(max_length=200, blank=True, default="")
    address_line2 = models.CharField(max_length=200, blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    pincode = models.CharField(max_length=6, blank=True, default="")
    payment_terms_days = models.PositiveSmallIntegerField(default=0)
    # Days from ordering to receiving; null = ⚙ planning.default_lead_days.
    lead_time_days = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_supplier_code"),
            models.UniqueConstraint(
                fields=["tenant", "gstin"],
                condition=Q(gstin__isnull=False, deleted_at__isnull=True),
                name="uniq_supplier_gstin",
            ),
        ]
        indexes = [
            GinIndex(fields=["name"], name="supplier_name_trgm", opclasses=["gin_trgm_ops"]),
            GinIndex(
                fields=["name_key"], name="supplier_name_key_trgm", opclasses=["gin_trgm_ops"]
            ),
            models.Index(fields=["tenant", "name"], name="supplier_name_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class SupplierProduct(TenantScopedModel):
    """A product a supplier can supply; one supplier per product is preferred."""

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="links")
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="supplier_links"
    )
    is_preferred = models.BooleanField(default=False)
    supplier_code = models.CharField(max_length=40, blank=True, default="")
    lead_time_days = models.PositiveSmallIntegerField(
        null=True, blank=True
    )  # null = the supplier's
    pack_size = QtyField(null=True, blank=True)  # order quantities round up to it (base unit)
    last_unit_cost = UnitCostField(null=True, blank=True)  # from posted receipts, before GST

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["supplier", "product"], name="uniq_supplier_product"),
            models.UniqueConstraint(
                fields=["tenant", "product"],
                condition=Q(is_preferred=True),
                name="uniq_preferred_supplier",
            ),
            models.CheckConstraint(
                condition=Q(pack_size__isnull=True) | Q(pack_size__gt=0),
                name="supplier_pack_positive",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "product"], name="supplier_product_idx")]

    def __str__(self) -> str:
        return f"{self.supplier_id}:{self.product_id}"


class PurchaseOrder(TenantScopedModel):
    """A purchase order to one supplier (ADR-053 item 5). Draft → Sent → Partly received →
    Received, or Closed (the rest cancelled, with a reason) or Cancelled (nothing received).
    Editable, and sent again as a revision, until something is received."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SENT = "SENT", "Sent"
        PARTLY_RECEIVED = "PARTLY_RECEIVED", "Partly received"
        RECEIVED = "RECEIVED", "Received"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"

    number = models.CharField(max_length=24)  # PO-2026-00001
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    warehouse = models.ForeignKey("inventory.Warehouse", on_delete=models.PROTECT, related_name="+")
    expected_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")  # printed for the supplier
    # What the supplier was sent (name, GSTIN, address, email, phone), fixed at each send.
    supplier_snapshot = models.JSONField(default=dict, blank=True)
    revision = models.PositiveSmallIntegerField(default=0)  # 0 until sent; 2+ = a revised copy
    changed_since_sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    closed_reason = models.CharField(max_length=300, blank=True, default="")
    # Before GST, for lines with a cost; GST estimated from each product's rate (information only).
    subtotal = MoneyField(default=0)
    estimated_tax = MoneyField(default=0)
    pdf_key = models.CharField(max_length=300, blank=True, default="")  # the supplier's copy
    plain_pdf_key = models.CharField(max_length=300, blank=True, default="")  # without prices
    pdf_status = models.CharField(
        max_length=8, choices=PdfStatus.choices, default=PdfStatus.PENDING
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="uniq_po_number"),
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "created_at"], name="po_status_idx"),
            models.Index(fields=["tenant", "supplier", "created_at"], name="po_supplier_idx"),
            models.Index(
                fields=["tenant", "expected_date"],
                condition=Q(status__in=["SENT", "PARTLY_RECEIVED"]),
                name="po_open_expected_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.number


class PurchaseOrderLine(TenantScopedModel):
    class EnteredUnit(models.TextChoices):
        BASE = "BASE", "Base unit"
        PACK = "PACK", "Pack"

    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    product_code = models.CharField(max_length=40)
    product_name = models.CharField(max_length=200)
    supplier_code = models.CharField(max_length=40, blank=True, default="")
    unit_code = models.CharField(max_length=10)
    entered_unit = models.CharField(max_length=4, choices=EnteredUnit.choices, default="BASE")
    entered_qty = QtyField()
    quantity = QtyField()  # base unit
    unit_cost = UnitCostField(null=True, blank=True)  # per base unit, before GST
    gst_rate = RateField(default=0)
    line_total = MoneyField(null=True, blank=True)  # quantity x cost, before GST
    qty_received = QtyField(default=0)
    qty_cancelled = QtyField(default=0)

    class Meta:
        ordering = ["line_no"]
        constraints = [
            models.UniqueConstraint(fields=["order", "line_no"], name="uniq_po_line_no"),
            models.CheckConstraint(
                condition=Q(quantity__gt=0)
                & Q(qty_received__gte=0)
                & Q(qty_cancelled__gte=0)
                & Q(qty_cancelled__lte=F("quantity")),
                name="po_line_quantities",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "product"], name="po_line_product_idx")]

    @property
    def due(self) -> Decimal:
        due: Decimal = max(self.quantity - self.qty_received - self.qty_cancelled, Decimal("0"))
        return due

    def __str__(self) -> str:
        return f"{self.order_id}:{self.line_no}"
