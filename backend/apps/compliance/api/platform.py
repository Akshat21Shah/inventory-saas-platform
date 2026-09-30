"""Super admin: a distributor's turnover band and what it suggests (ADR-049 item 3)."""

from typing import cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.models import User
from apps.compliance import turnover
from apps.compliance.api import serializers as s
from apps.platform.api.views import PlatformView
from apps.platform.models import Tenant
from common.errors import NotFound


class TenantTurnoverView(PlatformView):
    required_permission = "platform.tenants.manage"

    @staticmethod
    def _tenant(tenant_id: UUID) -> Tenant:
        tenant = Tenant.objects.filter(pk=tenant_id).first()
        if tenant is None:
            raise NotFound()
        return tenant

    @extend_schema(
        operation_id="platform_tenant_turnover", tags=["platform"], responses=s.TurnoverSerializer
    )
    def get(self, request: Request, tenant_id: UUID) -> Response:
        tenant = self._tenant(tenant_id)
        return Response(s.TurnoverSerializer(turnover.summary(tenant.pk)).data)

    @extend_schema(
        operation_id="platform_tenant_turnover_set",
        tags=["platform"],
        request=s.TurnoverInputSerializer,
        responses=s.TurnoverSerializer,
    )
    def put(self, request: Request, tenant_id: UUID) -> Response:
        tenant = self._tenant(tenant_id)
        data = s.TurnoverInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        body = turnover.set_band(
            tenant.pk, data.validated_data["turnover_band"], by=cast(User, request.user)
        )
        return Response(s.TurnoverSerializer(body).data)
