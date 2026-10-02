from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai import selectors
from apps.ai.api import serializers as s
from common.permissions import HasPermission, StaffReadsOrHasPermission


class MyAiUsageView(APIView):
    """This business's AI use this month in estimated rupees, questions and searches, against
    its monthly allowance (ADR-058, ADR-059 item 8)."""

    permission_classes = [StaffReadsOrHasPermission]
    required_permission = "settings.manage"

    @extend_schema(
        operation_id="settings_ai_usage", tags=["settings"], responses=s.MyAiUsageSerializer
    )
    def get(self, request: Request) -> Response:
        return Response(s.MyAiUsageSerializer(selectors.my_usage()).data)


class PlatformAiUsageView(APIView):
    """Each distributor's AI use this month, the dearest first, and what the monthly cap comes
    to in questions, searches and rupees (ADR-058, ADR-059 item 8)."""

    permission_classes = [HasPermission]
    required_permission = "platform.dashboard.view"

    @extend_schema(
        operation_id="platform_ai_usage",
        tags=["platform"],
        responses=s.PlatformAiUsageSerializer,
    )
    def get(self, request: Request) -> Response:
        return Response(s.PlatformAiUsageSerializer(selectors.platform_usage()).data)
