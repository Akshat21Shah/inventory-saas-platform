"""AI usage and product embeddings (ADR-058). Every row is a distributor's own (RLS)."""

from django.db import models

from apps.ai.adapters.base import DIMENSIONS
from common.models import TenantScopedModel
from common.vectors import HnswIndex, VectorField


class AiUsage(TenantScopedModel):
    """One call to a provider: what it was for and what it cost, never the text (append-only)."""

    class Feature(models.TextChoices):
        SEARCH_INDEX = "SEARCH_INDEX", "Product search: indexing products"
        SEARCH_QUERY = "SEARCH_QUERY", "Product search: a shop's search"
        ASSISTANT = "ASSISTANT", "Data assistant"

    feature = models.CharField(max_length=14, choices=Feature.choices)
    provider = models.CharField(max_length=20)
    model = models.CharField(max_length=60, blank=True, default="")
    units_in = models.PositiveIntegerField(default=0)
    units_out = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    ok = models.BooleanField(default=True)
    error = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["tenant", "created_at"], name="ai_usage_tenant_idx")]

    def __str__(self) -> str:
        return f"{self.feature} {self.units_in}+{self.units_out}"


class ProductEmbedding(TenantScopedModel):
    """A product's meaning as a vector, from the text in ``source_hash`` (re-made when it
    changes)."""

    product = models.OneToOneField(
        "catalog.Product", on_delete=models.CASCADE, related_name="ai_embedding"
    )
    vector = VectorField(dimensions=DIMENSIONS)
    source_hash = models.CharField(max_length=64)
    model = models.CharField(max_length=60)

    class Meta:
        indexes = [
            HnswIndex(
                fields=["vector"], name="product_embedding_hnsw", opclasses=["vector_cosine_ops"]
            )
        ]

    def __str__(self) -> str:
        return f"{self.product_id} ({self.model})"
