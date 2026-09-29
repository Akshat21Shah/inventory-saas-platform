"""Compliance APIs (PLAN §3.10): the distributor's GST provider credentials."""

from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.compliance import credentials
from apps.compliance.api import serializers as s
from common.permissions import HasPermission

TAGS = ["compliance"]


class GstCredentialsView(APIView):
    permission_classes = [HasPermission]
    required_permission = "settings.manage"

    @extend_schema(operation_id="gst_credentials", tags=TAGS, responses=s.GstCredentialsSerializer)
    def get(self, request: Request) -> Response:
        credentials.require_module()
        return Response(
            s.GstCredentialsSerializer(credentials.describe(credentials.current())).data
        )

    @extend_schema(
        operation_id="gst_credentials_save",
        tags=TAGS,
        request=s.GstCredentialsInputSerializer,
        responses=s.GstCredentialsSerializer,
    )
    def put(self, request: Request) -> Response:
        data = s.GstCredentialsInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = credentials.save(
            data.validated_data["environment"],
            data.validated_data["values"],
            by=cast(User, request.user),
        )
        return Response(s.GstCredentialsSerializer(credentials.describe(row)).data)


class GstCredentialsVerifyView(APIView):
    permission_classes = [HasPermission]
    required_permission = "settings.manage"

    @extend_schema(
        operation_id="gst_credentials_verify",
        tags=TAGS,
        request=None,
        responses=s.GstCredentialsSerializer,
    )
    def post(self, request: Request) -> Response:
        row = credentials.request_check()
        return Response(s.GstCredentialsSerializer(credentials.describe(row)).data)
