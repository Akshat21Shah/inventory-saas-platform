from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.insights import selectors, services
from apps.insights.api import serializers as s
from apps.insights.models import ShopActivity
from common import ratelimit
from common.errors import NotFound
from common.permissions import HasPermission
from common.tenancy import require_tenant_id

REFRESH_EVERY_SECONDS = 300


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


class MostUrgentFirst(CursorPagination):
    """Shops that stopped ordering first, then slowing, never ordered, new, active; within each,
    the longest wait first."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    ordering = ("-urgency", "id")


class ActivityListView(generics.ListAPIView[ShopActivity]):
    permission_classes = [HasPermission]
    required_permission = "retailers.view"
    serializer_class = s.ShopActivitySerializer
    pagination_class = MostUrgentFirst
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[ShopActivity]:
        if getattr(self, "swagger_fake_view", False):
            return ShopActivity.objects.unscoped().none()
        f = s.ActivityFilterSerializer(data=self.request.query_params)
        f.is_valid(raise_exception=True)
        v = f.validated_data
        return selectors.activity(
            _user(self.request),
            selectors.ActivityFilters(
                segment=v["segment"],
                salesperson_id=v["salesperson"],
                search=v["search"],
                win_back=v["win_back"],
            ),
        )

    def get_serializer_context(self) -> dict[str, Any]:
        return {
            **super().get_serializer_context(),
            "values": selectors.shows_values(_user(self.request)),
        }

    @extend_schema(
        parameters=[s.ActivityFilterSerializer],
        operation_id="shop_activity_list",
        tags=["insights"],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class ActivityRefreshView(APIView):
    """Work the figures out again now, in the background; once every five minutes."""

    permission_classes = [HasPermission]
    required_permission = "retailers.view"

    @extend_schema(
        operation_id="shop_activity_refresh",
        tags=["insights"],
        request=None,
        responses={202: s.ActivityRefreshSerializer},
    )
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        from apps.insights.tasks import refresh_for_tenant

        tenant = str(require_tenant_id())
        ratelimit.hit("shop-activity-refresh", tenant, 1, REFRESH_EVERY_SECONDS)
        transaction.on_commit(lambda: refresh_for_tenant.delay(tenant_id=tenant))
        return Response({"status": "QUEUED"}, status=202)


class ShopActivityView(APIView):
    """A shop's activity and its latest contacts (the shop's page)."""

    permission_classes = [HasPermission]
    required_permission = "retailers.view"

    @extend_schema(
        operation_id="retailer_activity",
        tags=["insights"],
        responses=s.ShopActivityDetailSerializer,
    )
    def get(self, request: Request, retailer_id: UUID) -> Response:
        from apps.retailers.selectors import retailers_for

        user = _user(request)
        if not retailers_for(user).filter(pk=retailer_id).exists():
            raise NotFound()
        found = selectors.shop_activity(user, retailer_id)
        context = {"values": selectors.shows_values(user)}
        return Response(
            {
                "activity": s.ShopActivitySerializer(found, context=context).data
                if found
                else None,
                "contacts": s.ShopContactSerializer(
                    selectors.contacts(retailer_id), many=True
                ).data,
            }
        )


class ShopContactCreateView(APIView):
    """Log a call, WhatsApp message or visit (ADR-056 item 3)."""

    permission_classes = [HasPermission]
    required_permission = "retailers.view"

    @extend_schema(
        operation_id="retailer_contact_create",
        tags=["insights"],
        request=s.ShopContactInputSerializer,
        responses={201: s.ShopContactSerializer},
    )
    def post(self, request: Request, retailer_id: UUID) -> Response:
        from apps.retailers.selectors import retailers_for

        user = _user(request)
        if not retailers_for(user).filter(pk=retailer_id).exists():
            raise NotFound()
        body = s.ShopContactInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        contact = services.log_contact(retailer_id, by=user, **body.validated_data)
        return Response(s.ShopContactSerializer(contact).data, status=201)
