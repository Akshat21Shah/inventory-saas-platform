"""Stock planning reads."""

from decimal import Decimal
from uuid import UUID

from django.db.models import Q, QuerySet, Value
from django.db.models.functions import Coalesce

from apps.catalog.models import Product
from apps.planning.models import ProductStats, ReorderSuggestion


def product_exists(product_id: UUID) -> bool:
    return Product.objects.filter(pk=product_id, deleted_at__isnull=True).exists()


def stats_for(product_id: UUID) -> ProductStats | None:
    stats: ProductStats | None = ProductStats.objects.filter(product_id=product_id).first()
    return stats


def open_suggestions(
    *, supplier_id: UUID | None = None, basis: str = "", search: str = ""
) -> QuerySet[ReorderSuggestion]:
    qs = (
        ReorderSuggestion.objects.filter(status=ReorderSuggestion.Status.OPEN)
        .select_related("product", "product__unit", "supplier")
        .annotate(urgency=Coalesce("days_left", Value(Decimal("-1"))))
    )
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)
    if basis:
        qs = qs.filter(basis=basis)
    term = " ".join(search.split())[:100]
    if term:
        qs = qs.filter(Q(product__name__icontains=term) | Q(product__code__iexact=term))
    found: QuerySet[ReorderSuggestion] = qs
    return found


def suggestion(suggestion_id: UUID) -> ReorderSuggestion | None:
    found: ReorderSuggestion | None = (
        ReorderSuggestion.objects.select_related("product", "product__unit", "supplier")
        .filter(pk=suggestion_id)
        .first()
    )
    return found


def open_suggestion_count() -> int:
    return ReorderSuggestion.objects.filter(status=ReorderSuggestion.Status.OPEN).count()
