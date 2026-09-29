"""The distributor's payment gateway settings (PLAN §3.10, ADR-049 items 7 and 11)."""

from typing import Any, cast

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.payments import gateway_config
from apps.payments.models import GatewayConfig
from common.permissions import HasPermission

TAGS = ["payments"]


class GatewaySettingsSerializer(serializers.Serializer[Any]):
    providers = serializers.ListField(child=serializers.ChoiceField(GatewayConfig.Provider.choices))
    provider = serializers.ChoiceField(choices=GatewayConfig.Provider.choices)
    mode = serializers.ChoiceField(choices=GatewayConfig.Mode.choices)
    live_allowed = serializers.BooleanField(help_text="Live keys may be used here.")
    saved = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        help_text="key_id, key_secret, webhook_secret: their last characters, never the value.",
    )
    status = serializers.ChoiceField(choices=GatewayConfig.Status.choices)
    verified_at = serializers.DateTimeField(allow_null=True)
    last_error = serializers.CharField(allow_blank=True)
    webhook_url = serializers.CharField(help_text="Enter this in the gateway's webhook settings.")


class GatewaySettingsInputSerializer(serializers.Serializer[Any]):
    provider = serializers.ChoiceField(choices=GatewayConfig.Provider.choices)
    mode = serializers.ChoiceField(choices=GatewayConfig.Mode.choices)
    key_id = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    key_secret = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    webhook_secret = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )


class GatewaySettingsView(APIView):
    permission_classes = [HasPermission]
    required_permission = "settings.manage"

    @extend_schema(operation_id="payment_gateway", tags=TAGS, responses=GatewaySettingsSerializer)
    def get(self, request: Request) -> Response:
        gateway_config.require_module()
        body = gateway_config.describe(gateway_config.current())
        return Response(GatewaySettingsSerializer(body).data)

    @extend_schema(
        operation_id="payment_gateway_save",
        tags=TAGS,
        request=GatewaySettingsInputSerializer,
        responses=GatewaySettingsSerializer,
    )
    def put(self, request: Request) -> Response:
        data = GatewaySettingsInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        row = gateway_config.save(
            v["provider"],
            v["mode"],
            {name: v[name] for name in gateway_config.SECRETS},
            by=cast(User, request.user),
        )
        return Response(GatewaySettingsSerializer(gateway_config.describe(row)).data)


class GatewayVerifyView(APIView):
    permission_classes = [HasPermission]
    required_permission = "settings.manage"

    @extend_schema(
        operation_id="payment_gateway_verify",
        tags=TAGS,
        request=None,
        responses=GatewaySettingsSerializer,
    )
    def post(self, request: Request) -> Response:
        row = gateway_config.request_check()
        return Response(GatewaySettingsSerializer(gateway_config.describe(row)).data)
