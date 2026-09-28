"""Ledger (PLAN §2.11). Phase 4 creates only the per-shop account row: the lock that serialises a
shop's orders and credit checks (lock order level L1, ADR-044). Phase 5 adds the entries."""

from django.db import models

from common.fields import MoneyField
from common.models import TenantScopedModel


class RetailerAccount(TenantScopedModel):
    retailer = models.OneToOneField(
        "retailers.Retailer", on_delete=models.PROTECT, related_name="account"
    )
    # + = the shop owes, - = advance. 0 until the ledger exists (Phase 5).
    balance = MoneyField(default=0)

    def __str__(self) -> str:
        return f"{self.retailer_id}: {self.balance}"
