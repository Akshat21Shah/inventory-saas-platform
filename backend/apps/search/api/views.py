from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.search import selectors, services
from apps.search.api import serializers as s
from common.permissions import HasPermission, IsTenantStaff

QUERY = OpenApiParameter(
    "q", str, required=True, description="What was typed (2 to 100 characters)."
)


def _text(request: Request) -> str:
    return request.query_params.get("q", "")


class SearchView(APIView):
    """Records matching the typed text, grouped by kind, within what the person's role may see
    (ADR-053). Never carries cost data."""

    permission_classes = [IsTenantStaff]

    @extend_schema(
        operation_id="search",
        tags=["search"],
        parameters=[QUERY],
        responses=s.SearchResultsSerializer,
    )
    def get(self, request: Request) -> Response:
        user: User = request.user  # type: ignore[assignment]
        return Response(s.SearchResultsSerializer(selectors.search(user, _text(request))).data)


class PlatformSearchView(APIView):
    """Distributors by name, legal name, GSTIN or web address."""

    permission_classes = [HasPermission]
    required_permission = "platform.tenants.manage"

    @extend_schema(
        operation_id="platform_search",
        tags=["platform"],
        parameters=[QUERY],
        responses=s.SearchResultsSerializer,
    )
    def get(self, request: Request) -> Response:
        return Response(s.SearchResultsSerializer(selectors.search_tenants(_text(request))).data)


class PlatformUserSearchView(APIView):
    """People across every distributor by name, email or mobile. Every search is audited."""

    permission_classes = [HasPermission]
    required_permission = "platform.tenants.manage"

    @extend_schema(
        operation_id="platform_search_users",
        tags=["platform"],
        parameters=[QUERY],
        responses=s.UserHitSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        return Response(s.UserHitSerializer(services.search_users(_text(request)), many=True).data)
