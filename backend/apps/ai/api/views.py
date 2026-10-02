from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai import selectors
from apps.ai.api import serializers as s
from common.permissions import HasPermission, StaffReadsOrHasPermission


class MyAiUsageView(APIView):
    """This business's AI use this month against its monthly limit (ADR-058)."""

    permission_classes = [StaffReadsOrHasPermission]
    required_permission = "settings.manage"

    @extend_schema(
        operation_id="settings_ai_usage", tags=["settings"], responses=s.MyAiUsageSerializer
    )
    def get(self, request: Request) -> Response:
        return Response(s.MyAiUsageSerializer(selectors.my_usage()).data)


class PlatformAiUsageView(APIView):
    """Each distributor's AI use this month, the heaviest first (ADR-058)."""

    permission_classes = [HasPermission]
    required_permission = "platform.dashboard.view"

    @extend_schema(
        operation_id="platform_ai_usage",
        tags=["platform"],
        responses=s.TenantAiUsageSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        return Response(s.TenantAiUsageSerializer(selectors.usage_by_tenant(), many=True).data)
