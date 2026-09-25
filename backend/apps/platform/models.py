"""Tenants. PHASE 0 STUB: only the fields TenantScopedModel needs; Phase 1 completes the model."""

from django.db import models

from common.models import BaseModel


class Tenant(BaseModel):
    class Status(models.TextChoices):
        ONBOARDING = "ONBOARDING", "Onboarding"
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=30, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ONBOARDING)

    def __str__(self) -> str:
        return self.name
