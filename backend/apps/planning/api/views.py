from typing import Any
from uuid import UUID

from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.planning import selectors
from apps.planning.api import serializers as s
from common import ratelimit
from common.errors import NotFound
from common.permissions import AnyOf, FeatureOn, HasPermission
from common.tenancy import require_tenant_id

REFRESH_EVERY_SECONDS = 300


class PlanningView(APIView):
    permission_classes = [HasPermission, FeatureOn]
    required_feature = "stock_planning"


class ProductStatsView(PlanningView):
    """A product's demand, days of stock and classes, as last worked out (ADR-053 item 3)."""

    required_permission = AnyOf(("purchasing.view", "stock.view"))

    @extend_schema(
        operation_id="product_stats",
        tags=["planning"],
        responses={
            200: s.ProductStatsSerializer,
            204: OpenApiResponse(description="Not worked out yet"),
        },
    )
    def get(self, request: Request, product_id: UUID) -> Response:
        if not selectors.product_exists(product_id):
            raise NotFound()
        stats = selectors.stats_for(product_id)
        if stats is None:
            return Response(status=204)
        return Response(s.ProductStatsSerializer(stats).data)


class StatsRefreshView(PlanningView):
    """Work the figures out again now, in the background; once every five minutes."""

    required_permission = "purchasing.manage"

    @extend_schema(
        operation_id="planning_stats_refresh",
        tags=["planning"],
        request=None,
        responses={202: s.PlanningRefreshSerializer},
    )
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        from apps.planning.tasks import refresh_for_tenant

        tenant = str(require_tenant_id())
        ratelimit.hit("planning-refresh", tenant, 1, REFRESH_EVERY_SECONDS)
        transaction.on_commit(lambda: refresh_for_tenant.delay(tenant_id=tenant))
        return Response({"status": "QUEUED"}, status=202)
