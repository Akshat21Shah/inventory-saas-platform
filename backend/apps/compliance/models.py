"""E-invoicing and e-way bills (PLAN §2.10, spec 5.11, ADR-049). Data only: the rules are in
``rules.py``, the work in the services, the GST provider behind ``adapters``."""

from django.conf import settings
from django.db import models
from django.db.models import Q

from common.crypto import EncryptedTextField
from common.models import TenantScopedModel

USER = settings.AUTH_USER_MODEL


class GstCredential(TenantScopedModel):
    """A distributor's own login with the GST provider (GSP). The provider's fields aren't known
    until one is chosen, so they are kept as encrypted JSON (``credentials``) and never returned
    in full."""

    class Environment(models.TextChoices):
        SANDBOX = "SANDBOX", "Sandbox"
        PRODUCTION = "PRODUCTION", "Production"

    class Status(models.TextChoices):
        UNVERIFIED = "UNVERIFIED", "Not checked"
        CHECKING = "CHECKING", "Checking"
        VERIFIED = "VERIFIED", "Working"
        FAILED = "FAILED", "Not working"

    provider = models.CharField(max_length=30)  # settings.GSP_PROVIDER when saved
    environment = models.CharField(
        max_length=10, choices=Environment.choices, default=Environment.SANDBOX
    )
    gstin = models.CharField(max_length=15)
    credentials = EncryptedTextField(default="")  # JSON object
    is_active = models.BooleanField(default=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNVERIFIED)
    verified_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True, default="")
    updated_by = models.ForeignKey(
        USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "provider"], name="uniq_gst_credential"),
        ]

    def __str__(self) -> str:
        return f"{self.provider} {self.gstin}"


class DocumentType(models.TextChoices):
    INVOICE = "INVOICE", "Invoice"
    CREDIT_NOTE = "CREDIT_NOTE", "Credit note"


class EInvoiceRecord(TenantScopedModel):
    """One document's journey through the Invoice Registration Portal: submitted in the
    background, retried when the portal is down, and GENERATED (IRN, acknowledgement, signed QR)
    or FAILED with the portal's reason. The document keeps a copy of the outcome for printing."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Waiting to be sent"
        SUBMITTED = "SUBMITTED", "Sent, waiting for the portal"
        GENERATED = "GENERATED", "IRN generated"
        FAILED = "FAILED", "IRN failed"
        CANCELLED = "CANCELLED", "IRN cancelled"

    class CancelOutcome(models.TextChoices):
        REISSUE = "REISSUE", "Re-issued with a new number"
        TAKE_BACK = "TAKE_BACK", "Goods taken back"

    document_type = models.CharField(max_length=11, choices=DocumentType.choices)
    invoice = models.ForeignKey(
        "billing.Invoice", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    credit_note = models.ForeignKey(
        "billing.CreditNote", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    document_number = models.CharField(max_length=16)
    document_number_key = models.CharField(max_length=16)  # upper case: duplicates by case
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.PENDING)
    irn = models.CharField(max_length=64, blank=True, default="")
    ack_no = models.CharField(max_length=20, blank=True, default="")
    ack_date = models.DateTimeField(null=True, blank=True)
    signed_invoice = models.TextField(blank=True, default="")
    signed_qr = models.TextField(blank=True, default="")
    request_document = models.JSONField(default=dict)  # our neutral document (``document.py``)
    response = models.JSONField(default=dict)  # the provider's last answer, as the adapter gave it
    error_code = models.CharField(max_length=30, blank=True, default="")
    error_message = models.CharField(max_length=500, blank=True, default="")
    retryable = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    cancel_reason_code = models.CharField(max_length=20, blank=True, default="")
    cancel_remarks = models.CharField(max_length=100, blank=True, default="")
    cancel_outcome = models.CharField(
        max_length=9, choices=CancelOutcome.choices, blank=True, default=""
    )
    reissued_invoice = models.ForeignKey(
        "billing.Invoice", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        USER, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(document_type="INVOICE", invoice__isnull=False, credit_note__isnull=True)
                    | Q(
                        document_type="CREDIT_NOTE",
                        invoice__isnull=True,
                        credit_note__isnull=False,
                    )
                ),
                name="einvoice_one_document",
            ),
            models.UniqueConstraint(
                fields=["invoice"], condition=Q(invoice__isnull=False), name="uniq_einvoice_invoice"
            ),
            models.UniqueConstraint(
                fields=["credit_note"],
                condition=Q(credit_note__isnull=False),
                name="uniq_einvoice_credit_note",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"], name="einvoice_status_idx"),
            models.Index(fields=["tenant", "document_number_key"], name="einvoice_number_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.document_number} {self.status}"
