"""Public platform metadata (no tenant data): lets clients check the API they are talking to."""

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class MetaSerializer(serializers.Serializer):  # type: ignore[type-arg]
    api_version = serializers.CharField()
    environment = serializers.CharField()
    platform_domain = serializers.CharField()
    display_time_zone = serializers.CharField()


class MetaView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(responses=MetaSerializer, operation_id="meta_retrieve", tags=["meta"])
    def get(self, request: Request) -> Response:
        data = {
            "api_version": settings.SPECTACULAR_SETTINGS["VERSION"],
            "environment": settings.ENVIRONMENT,
            "platform_domain": settings.PLATFORM_DOMAIN,
            "display_time_zone": settings.DISPLAY_TIME_ZONE,
        }
        return Response(MetaSerializer(data).data)
