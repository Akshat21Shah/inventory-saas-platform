"""Shop activity reads (ADR-056): every list goes through ``retailers_for``, so sales staff limited
to their own shops see only those."""

from dataclasses import dataclass
from uuid import UUID

from django.db.models import OuterRef, Q, QuerySet, Subquery

from apps.accounts.models import User
from apps.insights.models import ShopActivity, ShopContact
from apps.insights.services import win_back_filter
from apps.retailers.selectors import retailers_for
from common.tenancy import require_tenant_id


@dataclass(frozen=True)
class ActivityFilters:
    segment: str = ""
    salesperson_id: UUID | None = None
    search: str = ""
    win_back: bool = False


def shows_values(user: User) -> bool:
    """Order values are sales figures: only with a sales-report permission (ADR-056 item 4)."""
    return user.has_permission_code("reports.sales") or user.has_permission_code(
        "reports.sales_own"
    )


def activity(user: User, filters: ActivityFilters | None = None) -> QuerySet[ShopActivity]:
    f = filters or ActivityFilters()
    last = ShopContact.objects.filter(retailer_id=OuterRef("retailer_id")).order_by("-created_at")
    qs = (
        ShopActivity.objects.filter(retailer__in=retailers_for(user))
        .select_related("retailer", "retailer__salesperson")
        .annotate(
            last_outcome=Subquery(last.values("outcome")[:1]),
            last_contact_by=Subquery(last.values("by__full_name")[:1]),
        )
    )
    if f.segment:
        qs = qs.filter(segment=f.segment)
    if f.salesperson_id:
        qs = qs.filter(retailer__salesperson_id=f.salesperson_id)
    term = " ".join(f.search.split())[:100]
    if term:
        condition = (
            Q(retailer__shop_name__icontains=term)
            | Q(retailer__owner_name__icontains=term)
            | Q(retailer__code__iexact=term)
        )
        digits = "".join(ch for ch in term if ch.isdigit())
        if len(digits) >= 4:
            condition |= Q(retailer__mobile__contains=digits)
        qs = qs.filter(condition)
    if f.win_back:
        qs = qs.filter(win_back_filter(require_tenant_id()))
    found: QuerySet[ShopActivity] = qs
    return found


def win_back_count(user: User) -> int:
    return activity(user, ActivityFilters(win_back=True)).count()


def shop_activity(user: User, retailer_id: UUID) -> ShopActivity | None:
    found: ShopActivity | None = activity(user).filter(retailer_id=retailer_id).first()
    return found


def contacts(retailer_id: UUID, *, limit: int = 20) -> list[ShopContact]:
    return list(
        ShopContact.objects.filter(retailer_id=retailer_id)
        .select_related("by")
        .order_by("-created_at")[:limit]
    )
