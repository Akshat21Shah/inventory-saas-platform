from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.planning import selectors, suggestions
from apps.planning.api import serializers as s
from apps.planning.models import ReorderSuggestion
from apps.platform.selectors import is_feature_enabled
from common import ratelimit
from common.error_codes import ErrorCode
from common.errors import DomainError, NotFound
from common.idempotency import idempotent
from common.permissions import AnyOf, FeatureOn, HasPermission, Requirement
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


# --- Reorder suggestions ----------------------------------------------------------------------

READ_SUGGESTIONS = AnyOf(("purchasing.view", "stock.view"))


class UrgentFirst(CursorPagination):
    """Shops waiting (no daily demand) first, then the fewest days of stock left."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    ordering = ("urgency", "id")


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


def _context(request: Request) -> dict[str, Any]:
    return {"suppliers": _user(request).has_permission_code("purchasing.view")}


class SuggestionListView(PlanningView, generics.ListAPIView[ReorderSuggestion]):
    required_permission = READ_SUGGESTIONS
    serializer_class = s.ReorderSuggestionSerializer
    pagination_class = UrgentFirst
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[ReorderSuggestion]:
        if getattr(self, "swagger_fake_view", False):
            return ReorderSuggestion.objects.unscoped().none()
        f = s.SuggestionFilterSerializer(data=self.request.query_params)
        f.is_valid(raise_exception=True)
        v = f.validated_data
        return selectors.open_suggestions(
            supplier_id=v["supplier"], basis=v["basis"], search=v["search"]
        )

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), **_context(self.request)}

    @extend_schema(
        parameters=[s.SuggestionFilterSerializer],
        operation_id="reorder_suggestions_list",
        tags=["planning"],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class SuggestionDetailView(PlanningView):
    required_permissions: dict[str, Requirement] = {
        "GET": READ_SUGGESTIONS,
        "PATCH": "purchasing.manage",
    }

    def _body(self, request: Request, suggestion_id: UUID) -> Response:
        found = selectors.suggestion(suggestion_id)
        if found is None:
            raise NotFound()
        return Response(s.ReorderSuggestionSerializer(found, context=_context(request)).data)

    @extend_schema(
        responses=s.ReorderSuggestionSerializer,
        operation_id="reorder_suggestions_get",
        tags=["planning"],
    )
    def get(self, request: Request, suggestion_id: UUID) -> Response:
        return self._body(request, suggestion_id)

    @extend_schema(
        request=s.SuggestionChangeSerializer,
        responses=s.ReorderSuggestionSerializer,
        operation_id="reorder_suggestions_update",
        tags=["planning"],
    )
    def patch(self, request: Request, suggestion_id: UUID) -> Response:
        data = s.SuggestionChangeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        if v["dismiss"]:
            suggestions.dismiss(suggestion_id, until=v["until"], by=_user(request))
        elif "quantity" in v:
            suggestions.change_quantity(suggestion_id, v["quantity"], by=_user(request))
        return self._body(request, suggestion_id)


class SuggestionCreateOrdersView(PlanningView):
    """Draft purchase orders from suggestions, one per preferred supplier (purchasing on)."""

    required_permission = "purchasing.manage"

    @extend_schema(
        request=s.SuggestionIdsSerializer,
        responses={201: s.CreatedOrderSerializer(many=True)},
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, True)],
        operation_id="reorder_suggestions_create_orders",
        tags=["planning"],
    )
    @idempotent("planning.suggestions.create_orders")
    def post(self, request: Request) -> Response:
        if not is_feature_enabled("purchasing"):
            raise DomainError(
                "Purchasing isn't switched on for your business.",
                code=ErrorCode.MODULE_NOT_ENABLED,
                status_code=403,
            )
        data = s.SuggestionIdsSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        created = suggestions.create_orders(
            data.validated_data["suggestion_ids"], by=_user(request)
        )
        body = [
            {
                "id": order.pk,
                "number": order.number,
                "supplier_name": order.supplier.name,
                "line_count": order.lines.count(),
            }
            for order in created
        ]
        return Response(s.CreatedOrderSerializer(body, many=True).data, status=201)


class SuggestionApplyLevelsView(PlanningView):
    """Use the reorder points as the products' reorder levels (audited; never automatic)."""

    required_permission = AnyOf(("products.manage", "stock.adjust"))

    @extend_schema(
        request=s.SuggestionIdsSerializer,
        responses=s.LevelsAppliedSerializer,
        operation_id="reorder_suggestions_apply_levels",
        tags=["planning"],
    )
    def post(self, request: Request) -> Response:
        data = s.SuggestionIdsSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        changed = suggestions.apply_reorder_levels(
            data.validated_data["suggestion_ids"], by=_user(request)
        )
        return Response({"changed": changed})
