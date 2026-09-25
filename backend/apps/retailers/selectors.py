"""Retailer reads. Sales staff may be limited to their own shops (⚙ ``orders.sales_visibility``,
PLAN B8)."""

from dataclasses import dataclass
from uuid import UUID

from django.db.models import Q, QuerySet

from apps.accounts.models import Membership, User
from apps.platform.selectors import get_setting
from apps.retailers.models import Retailer
from common.tenancy import require_tenant_id


def sees_own_retailers_only(user: User) -> bool:
    """Sales staff (who may only report on their own shops) see just the shops assigned to them
    when the distributor chose ASSIGNED_RETAILERS."""
    if get_setting("orders.sales_visibility", require_tenant_id()) != "ASSIGNED_RETAILERS":
        return False
    return user.has_permission_code("reports.sales_own") and not user.has_permission_code(
        "reports.sales"
    )


@dataclass(frozen=True)
class RetailerFilters:
    search: str = ""
    status: str = ""
    salesperson_id: UUID | None = None
    state: str = ""
    tag: str = ""


def retailers_for(user: User, filters: RetailerFilters | None = None) -> QuerySet[Retailer]:
    f = filters or RetailerFilters()
    qs = Retailer.objects.filter(deleted_at__isnull=True).select_related("state", "salesperson")
    if sees_own_retailers_only(user):
        qs = qs.filter(salesperson=user)
    if f.status:
        qs = qs.filter(status=f.status)
    if f.salesperson_id:
        qs = qs.filter(salesperson_id=f.salesperson_id)
    if f.state:
        qs = qs.filter(state_id=f.state)
    if f.tag:
        qs = qs.filter(tags__contains=[f.tag.lower()])
    term = " ".join(f.search.split())
    if term:
        digits = "".join(ch for ch in term if ch.isdigit())
        condition = (
            Q(shop_name__icontains=term)
            | Q(owner_name__icontains=term)
            | Q(code__iexact=term)
            | Q(shop_name__trigram_word_similar=term)
        )
        if len(digits) >= 4:
            condition |= Q(mobile__contains=digits)
        qs = qs.filter(condition)
    return qs


def retailer_for(user: User, retailer_id: UUID) -> Retailer | None:
    found: Retailer | None = (
        retailers_for(user).prefetch_related("addresses__state").filter(pk=retailer_id).first()
    )
    return found


def salespeople() -> QuerySet[Membership]:
    """Active staff who can be assigned to shops."""
    return (
        Membership.objects.filter(is_active=True).select_related("user").order_by("user__full_name")
    )
