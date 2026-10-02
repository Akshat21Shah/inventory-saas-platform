"""A pgvector column and its cosine distance for Django (ADR-058 item 5), without another Python
package: vectors go to the database as ``'[0.1,0.2,…]'`` text and come back as lists of floats."""

from __future__ import annotations

from typing import Any

from django.contrib.postgres.indexes import PostgresIndex
from django.db import models
from django.db.models.expressions import Func


def literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"


class VectorField(models.Field):  # type: ignore[type-arg]
    description = "A pgvector vector"

    def __init__(self, *args: Any, dimensions: int, **kwargs: Any) -> None:
        self.dimensions = dimensions
        super().__init__(*args, **kwargs)

    def deconstruct(self) -> Any:
        name, path, args, kwargs = super().deconstruct()
        kwargs["dimensions"] = self.dimensions
        return name, path, args, kwargs

    def db_type(self, connection: Any) -> str:
        return f"vector({self.dimensions})"

    def get_prep_value(self, value: Any) -> Any:
        if value is None or isinstance(value, str):
            return value
        return literal([float(x) for x in value])

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> list[float] | None:
        if value is None:
            return None
        return [float(x) for x in str(value).strip("[]").split(",") if x]


class CosineDistance(Func):
    """``a <=> b``: 0 for the same direction, 2 for opposite."""

    arg_joiner = " <=> "
    template = "(%(expressions)s)"
    output_field = models.FloatField()


class HnswIndex(PostgresIndex):
    """``USING hnsw``; pass ``opclasses=["vector_cosine_ops"]``."""

    suffix = "hnsw"
