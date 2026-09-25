"""Import jobs (ADR-035). The uploaded file is the source of truth: validation and commit both
read it, so nothing half-validated is ever applied."""

from django.db import models

from common.models import TenantScopedModel


class ImportJob(TenantScopedModel):
    class Kind(models.TextChoices):
        PRODUCTS = "PRODUCTS", "Products"
        RETAILERS = "RETAILERS", "Retailers"
        SPECIAL_PRICES = "SPECIAL_PRICES", "Special prices"
        PRICE_LIST_ITEMS = "PRICE_LIST_ITEMS", "Price-list prices"
        DISCOUNT_RULES = "DISCOUNT_RULES", "Discount rules"

    class Mode(models.TextChoices):
        ADD_ONLY = "ADD_ONLY", "Add new only"
        ADD_OR_UPDATE = "ADD_OR_UPDATE", "Add new and update existing"

    class Status(models.TextChoices):
        VALIDATING = "VALIDATING", "Checking the file"
        VALIDATED = "VALIDATED", "Ready to import"
        FAILED = "FAILED", "Can't be imported"
        COMMITTING = "COMMITTING", "Importing"
        COMMITTED = "COMMITTED", "Imported"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    mode = models.CharField(max_length=20, choices=Mode.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.VALIDATING)
    file_name = models.CharField(max_length=200)
    file_key = models.CharField(max_length=300)
    report_key = models.CharField(max_length=300, blank=True, default="")
    # A problem with the whole file (missing columns, unreadable...), in plain language.
    problem = models.TextField(blank=True, default="")
    # {"total", "new", "update", "unchanged", "error", "changes"} after validation;
    # {"applied", "failed"} added after commit.
    counts = models.JSONField(default=dict, blank=True)
    # The first rows with errors and the first rows that change (with old → new values).
    errors = models.JSONField(default=list, blank=True)
    changes = models.JSONField(default=list, blank=True)
    notes = models.JSONField(default=list, blank=True)  # file-level notes (ignored columns...)
    validated_at = models.DateTimeField(null=True, blank=True)
    committed_at = models.DateTimeField(null=True, blank=True)
    committed_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["tenant", "kind", "created_at"], name="import_job_idx")]

    def __str__(self) -> str:
        return f"{self.kind} {self.file_name} ({self.status})"
