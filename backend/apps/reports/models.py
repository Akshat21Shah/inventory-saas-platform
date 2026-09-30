"""Report exports (ADR-050). The reports themselves are definitions in code (``registry``)."""

from django.conf import settings
from django.db import models

from common.models import TenantScopedModel


class ReportRun(TenantScopedModel):
    """One export: who asked, for which report and filters, and the file while it lasts."""

    class Format(models.TextChoices):
        XLSX = "XLSX", "Excel"
        PDF = "PDF", "PDF"

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Waiting"
        RUNNING = "RUNNING", "Being made"
        READY = "READY", "Ready"
        FAILED = "FAILED", "Failed"
        EXPIRED = "EXPIRED", "Expired"

    report_code = models.CharField(max_length=40)
    title = models.CharField(max_length=120)
    params = models.JSONField(default=dict)
    format = models.CharField(max_length=4, choices=Format.choices)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.QUEUED)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    # Fixed when asked: rows limited to the requester's own shops; cost columns allowed.
    own_shops = models.BooleanField(default=False)
    costs = models.BooleanField(default=False)
    file_key = models.CharField(max_length=300, blank=True, default="")
    file_name = models.CharField(max_length=150, blank=True, default="")
    row_count = models.PositiveIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        indexes = [
            models.Index(
                fields=["tenant", "requested_by", "-created_at"], name="report_run_mine_idx"
            ),
            models.Index(fields=["status", "expires_at"], name="report_run_expiry_idx"),
        ]
