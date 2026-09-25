"""Test-only models exercising the common base classes (installed only in test settings)."""

from django.db import models

from common.crypto import EncryptedTextField
from common.fields import MoneyField, QtyField
from common.models import BaseModel, TenantScopedModel


class Widget(TenantScopedModel):
    name = models.CharField(max_length=50)
    price = MoneyField(default=0)
    qty = QtyField(default=0)


class LedgerLike(BaseModel):
    note = models.CharField(max_length=50)


class SecretHolder(BaseModel):
    secret = EncryptedTextField(blank=True, default="")
    optional_secret = EncryptedTextField(null=True, blank=True)
