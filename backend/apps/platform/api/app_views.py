"""Settings the Android app reads before and after sign-in (ADR-061 item 6)."""

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.platform.app_client import app_config


class AppConfigSerializer(serializers.Serializer[Any]):
    min_version = serializers.CharField(
        help_text="Older app versions must update first (the API answers 426 APP_UPDATE_REQUIRED)."
    )
    latest_version = serializers.CharField(
        allow_blank=True, help_text="The newest version in the Play Store; empty: unknown."
    )
    privacy_policy_url = serializers.CharField(
        allow_blank=True, help_text="The privacy policy, for the app's Privacy and data page."
    )


class AppConfigView(APIView):
    """Public: an app too old to sign in must still learn that it has to update."""

    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(responses=AppConfigSerializer, operation_id="app_config", tags=["public"])
    def get(self, request: Request) -> Response:
        return Response(AppConfigSerializer(app_config()).data)
