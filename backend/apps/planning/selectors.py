"""Stock planning reads."""

from uuid import UUID

from apps.catalog.models import Product
from apps.planning.models import ProductStats


def product_exists(product_id: UUID) -> bool:
    return Product.objects.filter(pk=product_id, deleted_at__isnull=True).exists()


def stats_for(product_id: UUID) -> ProductStats | None:
    stats: ProductStats | None = ProductStats.objects.filter(product_id=product_id).first()
    return stats
