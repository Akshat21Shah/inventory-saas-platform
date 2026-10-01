"""Suppliers and what they supply (ADR-053 items 4 to 6, flag ``purchasing``). Purchasing never
touches the shops' ledger; stock still changes only through goods receipts."""

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Q

from common.fields import QtyField, UnitCostField
from common.models import SoftDeleteMixin, TenantScopedModel


class Supplier(SoftDeleteMixin, TenantScopedModel):
    code = models.CharField(max_length=20)  # S-0001, allocated per tenant
    name = models.CharField(max_length=200)
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
