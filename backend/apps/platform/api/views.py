"""Super admin API (PLAN §3.3) and public reference data. Thin: validate → service → response.

Every endpoint needs a ``platform.*`` permission, which only PLATFORM users hold; the
authentication layer also refuses platform tokens outside the admin host (ADR-020).
"""

from typing import Any
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.staff_serializers import MembershipSerializer
from apps.accounts.models import Membership, User
from apps.audit import selectors as audit_selectors
from apps.audit.api.serializers import AuditFilterSerializer, AuditLogSerializer
from apps.audit.models import AuditLog
from apps.platform import master_services, platform_selectors, registry, services, tenant_services
from apps.platform.api import serializers as s
from apps.platform.models import CessType, FeatureFlag, HsnRateHint, Plan, State, TaxRate, Tenant
from apps.platform.selectors import current_plan, effective_features, platform_settings
from apps.platform.tenant_services import OnboardingInput
from common.errors import NotFound
from common.permissions import HasPermission


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


class PlatformView(APIView):
    permission_classes = [HasPermission]


# --- Public reference data ----------------------------------------------------------------------


class PublicStatesView(generics.ListAPIView[State]):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    serializer_class = s.StateSerializer
    pagination_class = None
    queryset = State.objects.filter(is_active=True).order_by("name")

    @extend_schema(operation_id="public_states_list", tags=["public"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


# --- Tenants ------------------------------------------------------------------------------------


class TenantListCreateView(PlatformView, generics.ListAPIView[Tenant]):
    required_permission = "platform.tenants.manage"
    serializer_class = s.TenantListSerializer

    def get_queryset(self) -> Any:
        return platform_selectors.tenants_overview(
            status=self.request.query_params.get("status") or None,
            search=self.request.query_params.get("search") or None,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, enum=[c.value for c in Tenant.Status]),
            OpenApiParameter("search", str),
        ],
        operation_id="platform_tenants_list",
        tags=["platform"],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.OnboardingSerializer,
        responses={201: s.TenantDetailSerializer},
        operation_id="platform_tenants_create",
        tags=["platform"],
    )
    def post(self, request: Request) -> Response:
        data = s.OnboardingSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = dict(data.validated_data)
        v["state_id"] = v.pop("state_code")
        tenant = tenant_services.onboard_tenant(OnboardingInput(**v), by=_user(request))
        return Response(_tenant_detail(tenant.pk), status=201)


def _tenant_detail(tenant_id: UUID) -> Any:
    tenant = platform_selectors.tenant_detail(tenant_id)
    if tenant is None:
        raise NotFound()
    context = {
        "usage": platform_selectors.tenant_usage(tenant_id),
        "owner": platform_selectors.tenant_owner(tenant_id),
        "features": effective_features(tenant_id),
    }
    return s.TenantDetailSerializer(tenant, context=context).data


class TenantDetailView(PlatformView):
    required_permission = "platform.tenants.manage"

    @extend_schema(
        responses=s.TenantDetailSerializer,
        operation_id="platform_tenants_retrieve",
        tags=["platform"],
    )
    def get(self, request: Request, tenant_id: UUID) -> Response:
        return Response(_tenant_detail(tenant_id))

    @extend_schema(
        request=s.TenantUpdateSerializer,
        responses=s.TenantDetailSerializer,
        operation_id="platform_tenants_update",
        tags=["platform"],
    )
    def patch(self, request: Request, tenant_id: UUID) -> Response:
        data = s.TenantUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        changes = dict(data.validated_data)
        confirm = changes.pop("confirm_slug_change", False)
        if "state_code" in changes:
            changes["state_id"] = changes.pop("state_code")
        tenant_services.update_tenant(
            tenant_id, changes, by=_user(request), confirm_slug_change=confirm
        )
        return Response(_tenant_detail(tenant_id))


class SlugAvailabilityView(PlatformView):
    required_permission = "platform.tenants.manage"

    @extend_schema(
        parameters=[OpenApiParameter("slug", str, required=True)],
        responses=s.SlugAvailabilitySerializer,
        operation_id="platform_tenants_slug_available",
        tags=["platform"],
    )
    def get(self, request: Request) -> Response:
        slug = (request.query_params.get("slug") or "").strip().lower()
        return Response({"slug": slug, "available": tenant_services.slug_available(slug)})


class TenantSuspendView(PlatformView):
    required_permission = "platform.tenants.manage"

    @extend_schema(
        request=s.ReasonSerializer,
        responses=s.TenantDetailSerializer,
        operation_id="platform_tenants_suspend",
        tags=["platform"],
    )
    def post(self, request: Request, tenant_id: UUID) -> Response:
        data = s.ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        tenant_services.suspend_tenant(
            tenant_id, reason=data.validated_data["reason"], by=_user(request)
        )
        return Response(_tenant_detail(tenant_id))


class TenantReactivateView(PlatformView):
    required_permission = "platform.tenants.manage"

    @extend_schema(
        request=None,
        responses=s.TenantDetailSerializer,
        operation_id="platform_tenants_reactivate",
        tags=["platform"],
    )
    def post(self, request: Request, tenant_id: UUID) -> Response:
        tenant_services.reactivate_tenant(tenant_id, by=_user(request))
        return Response(_tenant_detail(tenant_id))


class TenantFeaturesView(PlatformView):
    required_permission = "platform.flags.manage"

    @extend_schema(
        responses={200: {"type": "object", "additionalProperties": {"type": "boolean"}}},
        operation_id="platform_tenant_features",
        tags=["platform"],
    )
    def get(self, request: Request, tenant_id: UUID) -> Response:
        if not Tenant.objects.filter(pk=tenant_id).exists():
            raise NotFound()
        return Response(effective_features(tenant_id))


class TenantFeatureToggleView(PlatformView):
    required_permission = "platform.flags.manage"

    @extend_schema(
        request=s.FeatureToggleSerializer,
        responses=s.FeatureToggleSerializer,
        operation_id="platform_tenant_feature_set",
        tags=["platform"],
    )
    def put(self, request: Request, tenant_id: UUID, code: str) -> Response:
        data = s.FeatureToggleSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        enabled = tenant_services.set_tenant_feature(
            tenant_id, code, data.validated_data["enabled"], by=_user(request)
        )
        return Response({"enabled": enabled})


class TenantSubscriptionView(PlatformView):
    required_permissions = {"GET": "platform.plans.manage", "PUT": "platform.plans.manage"}

    def _body(self, tenant_id: UUID) -> dict[str, Any]:
        if not Tenant.objects.filter(pk=tenant_id).exists():
            raise NotFound()
        plan = current_plan(tenant_id)
        return {
            "plan": {"code": plan.code, "name": plan.name},
            "status": "ACTIVE",
            "starts_at": None,
        }

    @extend_schema(
        responses=s.SubscriptionSerializer,
        operation_id="platform_tenant_subscription",
        tags=["platform"],
    )
    def get(self, request: Request, tenant_id: UUID) -> Response:
        from apps.platform.models import Subscription
        from common.platform_db import platform_db

        body = self._body(tenant_id)
        sub = (
            Subscription.objects.unscoped()
            .using(platform_db("platform.tenant_subscription"))
            .filter(tenant_id=tenant_id, is_current=True)
            .first()
        )
        if sub is not None:
            body.update(status=sub.status, starts_at=sub.starts_at)
        return Response(s.SubscriptionSerializer(body).data)

    @extend_schema(
        request=s.ChangePlanSerializer,
        responses=s.SubscriptionSerializer,
        operation_id="platform_tenant_subscription_update",
        tags=["platform"],
    )
    def put(self, request: Request, tenant_id: UUID) -> Response:
        data = s.ChangePlanSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        sub = tenant_services.change_plan(
            tenant_id, data.validated_data["plan_code"], by=_user(request)
        )
        return Response(
            s.SubscriptionSerializer(
                {
                    "plan": {"code": sub.plan.code, "name": sub.plan.name},
                    "status": sub.status,
                    "starts_at": sub.starts_at,
                }
            ).data
        )


class TenantUsersView(PlatformView, generics.ListAPIView[Membership]):
    required_permission = "platform.tenants.manage"
    serializer_class = MembershipSerializer

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):
            return Membership.objects.unscoped().none()
        tenant_id = self.kwargs["tenant_id"]
        if not Tenant.objects.filter(pk=tenant_id).exists():
            raise NotFound()
        return platform_selectors.tenant_staff(tenant_id)

    @extend_schema(operation_id="platform_tenant_users", tags=["platform"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class TenantOwnerResendView(PlatformView):
    required_permission = "platform.tenants.manage"

    @extend_schema(
        request=None,
        responses={202: None},
        operation_id="platform_tenant_owner_resend_invite",
        tags=["platform"],
    )
    def post(self, request: Request, tenant_id: UUID) -> Response:
        tenant_services.resend_owner_invitation(tenant_id, by=_user(request))
        return Response(status=202)


class DashboardView(PlatformView):
    required_permission = "platform.dashboard.view"

    @extend_schema(
        responses=s.DashboardSerializer, operation_id="platform_dashboard", tags=["platform"]
    )
    def get(self, request: Request) -> Response:
        return Response(s.DashboardSerializer(platform_selectors.platform_counts()).data)


# --- Plans & flag catalogue ---------------------------------------------------------------------


class PlanListCreateView(PlatformView, generics.ListAPIView[Plan]):
    required_permission = "platform.plans.manage"
    serializer_class = s.PlanSerializer
    queryset = Plan.objects.all()
    pagination_class = None

    @extend_schema(operation_id="platform_plans_list", tags=["platform"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.PlanSerializer,
        responses={201: s.PlanSerializer},
        operation_id="platform_plans_create",
        tags=["platform"],
    )
    def post(self, request: Request) -> Response:
        data = s.PlanSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        plan = master_services.create_plan(dict(data.validated_data), by=_user(request))
        return Response(s.PlanSerializer(plan).data, status=201)


class PlanDetailView(PlatformView):
    required_permission = "platform.plans.manage"

    @extend_schema(
        request=s.PlanUpdateSerializer,
        responses=s.PlanSerializer,
        operation_id="platform_plans_update",
        tags=["platform"],
    )
    def patch(self, request: Request, plan_id: UUID) -> Response:
        data = s.PlanUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        plan = master_services.update_plan(plan_id, dict(data.validated_data), by=_user(request))
        return Response(s.PlanSerializer(plan).data)


class FeatureFlagListView(PlatformView, generics.ListAPIView[FeatureFlag]):
    required_permission = "platform.flags.manage"
    serializer_class = s.FeatureFlagSerializer
    queryset = FeatureFlag.objects.all()
    pagination_class = None

    @extend_schema(operation_id="platform_feature_flags_list", tags=["platform"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class FeatureFlagDetailView(PlatformView):
    required_permission = "platform.flags.manage"

    @extend_schema(
        request=s.FeatureFlagSerializer,
        responses=s.FeatureFlagSerializer,
        operation_id="platform_feature_flags_update",
        tags=["platform"],
    )
    def patch(self, request: Request, code: str) -> Response:
        data = s.FeatureFlagSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        flag = master_services.update_feature_flag(
            code, dict(data.validated_data), by=_user(request)
        )
        return Response(s.FeatureFlagSerializer(flag).data)


# --- Tax masters --------------------------------------------------------------------------------


class TaxRateListCreateView(PlatformView, generics.ListAPIView[TaxRate]):
    required_permission = "platform.settings.manage"
    serializer_class = s.TaxRateSerializer
    queryset = TaxRate.objects.all()
    pagination_class = None

    @extend_schema(operation_id="platform_tax_rates_list", tags=["platform"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.TaxRateSerializer,
        responses={201: s.TaxRateSerializer},
        operation_id="platform_tax_rates_create",
        tags=["platform"],
    )
    def post(self, request: Request) -> Response:
        data = s.TaxRateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        rate = master_services.create_tax_rate(
            rate=v["rate"], label=v["label"], notes=v.get("notes", ""), by=_user(request)
        )
        return Response(s.TaxRateSerializer(rate).data, status=201)


class TaxRateDetailView(PlatformView):
    required_permission = "platform.settings.manage"

    @extend_schema(
        request=s.TaxRateUpdateSerializer,
        responses=s.TaxRateSerializer,
        operation_id="platform_tax_rates_update",
        tags=["platform"],
    )
    def patch(self, request: Request, tax_rate_id: UUID) -> Response:
        data = s.TaxRateUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        rate = master_services.update_tax_rate(
            tax_rate_id, dict(data.validated_data), by=_user(request)
        )
        return Response(s.TaxRateSerializer(rate).data)


class CessTypeListCreateView(PlatformView, generics.ListAPIView[CessType]):
    required_permission = "platform.settings.manage"
    serializer_class = s.CessTypeSerializer
    queryset = CessType.objects.all()
    pagination_class = None

    @extend_schema(operation_id="platform_cess_types_list", tags=["platform"])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.CessTypeSerializer,
        responses={201: s.CessTypeSerializer},
        operation_id="platform_cess_types_create",
        tags=["platform"],
    )
    def post(self, request: Request) -> Response:
        data = s.CessTypeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        cess = master_services.create_cess_type(dict(data.validated_data), by=_user(request))
        return Response(s.CessTypeSerializer(cess).data, status=201)


class CessTypeDetailView(PlatformView):
    required_permission = "platform.settings.manage"

    @extend_schema(
        request=s.CessTypeUpdateSerializer,
        responses=s.CessTypeSerializer,
        operation_id="platform_cess_types_update",
        tags=["platform"],
    )
    def patch(self, request: Request, cess_id: UUID) -> Response:
        data = s.CessTypeUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        cess = master_services.update_cess_type(
            cess_id, dict(data.validated_data), by=_user(request)
        )
        return Response(s.CessTypeSerializer(cess).data)


class HsnHintListCreateView(PlatformView, generics.ListAPIView[HsnRateHint]):
    required_permission = "platform.settings.manage"
    serializer_class = s.HsnHintSerializer

    def get_queryset(self) -> Any:
        qs = HsnRateHint.objects.all()
        prefix = self.request.query_params.get("prefix")
        return qs.filter(hsn_prefix__startswith=prefix) if prefix else qs

    @extend_schema(
        parameters=[OpenApiParameter("prefix", str)],
        operation_id="platform_hsn_hints_list",
        tags=["platform"],
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=s.HsnHintSerializer,
        responses={201: s.HsnHintSerializer},
        operation_id="platform_hsn_hints_create",
        tags=["platform"],
    )
    def post(self, request: Request) -> Response:
        data = s.HsnHintSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        hint = master_services.create_hsn_hint(dict(data.validated_data), by=_user(request))
        return Response(s.HsnHintSerializer(hint).data, status=201)


class HsnHintDetailView(PlatformView):
    required_permission = "platform.settings.manage"

    @extend_schema(
        request=s.HsnHintUpdateSerializer,
        responses=s.HsnHintSerializer,
        operation_id="platform_hsn_hints_update",
        tags=["platform"],
    )
    def patch(self, request: Request, hint_id: UUID) -> Response:
        data = s.HsnHintUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        hint = master_services.update_hsn_hint(
            hint_id, dict(data.validated_data), by=_user(request)
        )
        return Response(s.HsnHintSerializer(hint).data)

    @extend_schema(
        responses={204: None}, operation_id="platform_hsn_hints_delete", tags=["platform"]
    )
    def delete(self, request: Request, hint_id: UUID) -> Response:
        master_services.delete_hsn_hint(hint_id, by=_user(request))
        return Response(status=204)


class HsnHintImportView(PlatformView):
    required_permission = "platform.settings.manage"
    parser_classes = [MultiPartParser]

    @extend_schema(
        request={"multipart/form-data": s.HsnImportSerializer},
        responses=s.HsnImportResultSerializer,
        operation_id="platform_hsn_hints_import",
        tags=["platform"],
    )
    def post(self, request: Request) -> Response:
        data = s.HsnImportSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        upload = data.validated_data["file"]
        content = upload.read(master_services.HSN_IMPORT_MAX_BYTES + 1)
        result = master_services.import_hsn_hints(content, by=_user(request))
        return Response(s.HsnImportResultSerializer(result).data)


# --- Platform settings & audit ------------------------------------------------------------------


class PlatformSettingsRegistryView(PlatformView):
    required_permission = "platform.settings.manage"

    @extend_schema(
        responses=s.SettingSerializer(many=True),
        operation_id="platform_settings_registry",
        tags=["platform"],
    )
    def get(self, request: Request) -> Response:
        rows = s.setting_rows(
            platform_settings(), registry.Scope.PLATFORM, _user(request).permission_codes()
        )
        return Response(s.SettingSerializer(rows, many=True).data)


class PlatformSettingsValuesView(PlatformView):
    required_permission = "platform.settings.manage"

    @extend_schema(
        request=s.SettingValuesSerializer,
        responses=s.SettingSerializer(many=True),
        operation_id="platform_settings_update",
        tags=["platform"],
    )
    def patch(self, request: Request) -> Response:
        data = s.SettingValuesSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = services.set_platform_settings(data.validated_data["values"], user=_user(request))
        rows = s.setting_rows(values, registry.Scope.PLATFORM, _user(request).permission_codes())
        return Response(s.SettingSerializer(rows, many=True).data)


class PlatformAuditLogView(PlatformView, generics.ListAPIView[AuditLog]):
    required_permission = "platform.audit.view"
    serializer_class = AuditLogSerializer

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):
            return AuditLog.objects.none()
        filters = AuditFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        f = dict(filters.validated_data)
        tenant_id = f.pop("tenant_id", None)
        return audit_selectors.platform_audit_logs(f, tenant_id=tenant_id)  # type: ignore[arg-type]

    @extend_schema(
        parameters=[AuditFilterSerializer], operation_id="platform_audit_logs", tags=["platform"]
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)
