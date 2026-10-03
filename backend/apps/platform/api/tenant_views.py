"""Distributor settings, branding, feature flags and the tenant audit log (PLAN §3.4), plus the
public branding a tenant's pre-login pages need (PLAN §3.2)."""

from typing import Any
from uuid import UUID

from django.http import HttpResponseRedirect
from django.utils.translation import gettext
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.audit import selectors as audit_selectors
from apps.audit.api.serializers import AuditFilterSerializer, AuditLogSerializer
from apps.audit.models import AuditLog
from apps.platform import registry, services, tenant_services, tenant_settings_services
from apps.platform.api import tenant_serializers as s
from apps.platform.api.serializers import (
    FeatureToggleSerializer,
    SettingSerializer,
    SettingValuesSerializer,
    setting_rows,
)
from apps.platform.models import FeatureFlag, Tenant, TenantBranding, TenantProfile
from apps.platform.selectors import (
    branding_body,
    effective_features,
    public_branding,
    tenant_by_slug,
    tenant_settings,
)
from common.error_codes import ErrorCode
from common.errors import DomainError, NotFound
from common.numbers import fill
from common.permissions import HasPermission, StaffReadsOrHasPermission
from common.storage import get_storage
from common.tenancy import require_tenant_id, tenant_context


def _user(request: Request) -> User:
    user: User = request.user  # type: ignore[assignment]
    return user


# --- Business & bank details --------------------------------------------------------------------


def _business(tenant: Tenant, profile: TenantProfile) -> dict[str, Any]:
    return {
        "name": tenant.name,
        "legal_name": tenant.legal_name,
        "gstin": tenant.gstin,
        "pan": tenant.pan,
        "state_code": tenant.state_id,
        "registration_type": tenant.registration_type,
        "slug": tenant.slug,
        "address_line1": tenant.address_line1,
        "address_line2": tenant.address_line2,
        "city": tenant.city,
        "pincode": tenant.pincode,
        "email": tenant.email,
        "phone": tenant.phone,
        "invoice_terms": profile.invoice_terms,
        "invoice_footer": profile.invoice_footer,
        "signatory_name": profile.signatory_name,
        "has_signatory_image": bool(profile.signatory_image),
        "gst_identity_locked": tenant_services.gst_identity_locked(tenant.pk),
    }


def _load_business() -> dict[str, Any]:
    tenant = Tenant.objects.get(pk=require_tenant_id())
    profile, _ = TenantProfile.objects.get_or_create()
    return _business(tenant, profile)


class BusinessSettingsView(APIView):
    permission_classes = [StaffReadsOrHasPermission]
    required_permission = "settings.manage"

    @extend_schema(
        responses=s.BusinessSerializer, operation_id="settings_business", tags=["settings"]
    )
    def get(self, request: Request) -> Response:
        return Response(s.BusinessSerializer(_load_business()).data)

    @extend_schema(
        request=s.BusinessSerializer,
        responses=s.BusinessSerializer,
        operation_id="settings_business_update",
        tags=["settings"],
    )
    def patch(self, request: Request) -> Response:
        data = s.BusinessSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        changes = dict(data.validated_data)
        if "state_code" in changes:
            changes["state_id"] = changes.pop("state_code")
        tenant_settings_services.update_business(changes, by=_user(request))
        return Response(s.BusinessSerializer(_load_business()).data)


class BankDetailsView(APIView):
    """Bank details are never changed during impersonation (ADR-029)."""

    permission_classes = [HasPermission]
    required_permission = "settings.manage"
    impersonation_blocked = True

    @extend_schema(
        responses=s.BankDetailsSerializer, operation_id="settings_bank_details", tags=["settings"]
    )
    def get(self, request: Request) -> Response:
        profile, _ = TenantProfile.objects.get_or_create()
        return Response(tenant_settings_services.bank_details(profile))

    @extend_schema(
        request=s.BankDetailsInputSerializer,
        responses=s.BankDetailsSerializer,
        operation_id="settings_bank_details_update",
        tags=["settings"],
    )
    def put(self, request: Request) -> Response:
        data = s.BankDetailsInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        profile = tenant_settings_services.update_bank_details(
            dict(data.validated_data), by=_user(request)
        )
        return Response(tenant_settings_services.bank_details(profile))


# --- Commercial settings (registry, ADR-016) ----------------------------------------------------


def _settings_rows(request: Request, *, fresh: bool = False) -> Any:
    """After a change in this request, read fresh: the cache is only invalidated on commit."""
    values = tenant_settings(fresh=fresh)
    permissions = _user(request).permission_codes()
    rows = setting_rows(values, registry.Scope.TENANT, permissions, effective_features())
    return SettingSerializer(rows, many=True).data


def _require_edit_permission(request: Request, keys: list[str]) -> None:
    features = effective_features()
    if any(
        k in registry.REGISTRY and not registry.module_on(registry.REGISTRY[k], features)
        for k in keys
    ):
        raise DomainError(
            gettext("This setting belongs to a module that isn't switched on for your business."),
            code=ErrorCode.MODULE_NOT_ENABLED,
            status_code=403,
        )
    permissions = _user(request).permission_codes()
    denied = [
        k
        for k in keys
        if k in registry.REGISTRY and registry.REGISTRY[k].required_permission not in permissions
    ]
    if denied:
        raise PermissionDenied(
            fill(gettext("You can't change: %(denied)s."), {"denied": ", ".join(sorted(denied))})
        )


class TenantSettingsRegistryView(APIView):
    permission_classes = [StaffReadsOrHasPermission]

    @extend_schema(
        responses=SettingSerializer(many=True), operation_id="settings_registry", tags=["settings"]
    )
    def get(self, request: Request) -> Response:
        return Response(_settings_rows(request))


class TenantSettingsValuesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=SettingValuesSerializer,
        responses=SettingSerializer(many=True),
        operation_id="settings_values_update",
        tags=["settings"],
    )
    def patch(self, request: Request) -> Response:
        data = SettingValuesSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data["values"]
        _require_edit_permission(request, list(values))
        services.set_tenant_settings(values, user=_user(request))
        return Response(_settings_rows(request, fresh=True))


class TenantSettingResetView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={200: SettingSerializer(many=True)},
        operation_id="settings_value_reset",
        tags=["settings"],
    )
    def delete(self, request: Request, key: str) -> Response:
        _require_edit_permission(request, [key])
        services.reset_tenant_setting(key, user=_user(request))
        return Response(_settings_rows(request, fresh=True))


# --- Branding & assets --------------------------------------------------------------------------


def _load_branding() -> dict[str, Any]:
    tenant = Tenant.objects.get(pk=require_tenant_id())
    branding, _ = TenantBranding.objects.get_or_create()
    return branding_body(tenant, branding)


class BrandingView(APIView):
    permission_classes = [StaffReadsOrHasPermission]
    required_permission = "branding.manage"

    @extend_schema(
        responses=s.BrandingSerializer, operation_id="settings_branding", tags=["settings"]
    )
    def get(self, request: Request) -> Response:
        return Response(s.BrandingSerializer(_load_branding()).data)

    @extend_schema(
        request=s.BrandingSerializer,
        responses=s.BrandingSerializer,
        operation_id="settings_branding_update",
        tags=["settings"],
    )
    def patch(self, request: Request) -> Response:
        data = s.BrandingSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        tenant_settings_services.update_branding(dict(data.validated_data), by=_user(request))
        return Response(s.BrandingSerializer(_load_branding()).data)


class BrandingAssetView(APIView):
    """Upload or remove a logo, favicon, app icon (``branding.manage``) or the authorised
    signatory's image (``settings.manage``)."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def _check(self, request: Request, kind: str) -> None:
        if kind not in tenant_settings_services.ASSET_KINDS:
            raise NotFound()
        needed = "settings.manage" if kind == "signatory" else "branding.manage"
        if not _user(request).has_permission_code(needed):
            raise PermissionDenied()

    @extend_schema(
        request={"multipart/form-data": s.AssetUploadSerializer},
        responses=s.BrandingSerializer,
        operation_id="settings_branding_asset_upload",
        tags=["settings"],
    )
    def post(self, request: Request, kind: str) -> Response:
        self._check(request, kind)
        data = s.AssetUploadSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        tenant_settings_services.upload_asset(kind, data.validated_data["file"], by=_user(request))
        return Response(s.BrandingSerializer(_load_branding()).data, status=201)

    @extend_schema(
        request=None,
        responses={200: s.BrandingSerializer},
        operation_id="settings_branding_asset_delete",
        tags=["settings"],
    )
    def delete(self, request: Request, kind: str) -> Response:
        self._check(request, kind)
        tenant_settings_services.remove_asset(kind, by=_user(request))
        return Response(s.BrandingSerializer(_load_branding()).data)


class SignatoryImageView(APIView):
    """The signatory image is never public: staff with ``settings.manage`` get a short link."""

    permission_classes = [HasPermission]
    required_permission = "settings.manage"

    @extend_schema(
        responses={302: OpenApiResponse(description="Redirect to a short-lived download link")},
        operation_id="settings_signatory_image",
        tags=["settings"],
    )
    def get(self, request: Request) -> HttpResponseRedirect:
        profile = TenantProfile.objects.first()
        if profile is None or not profile.signatory_image:
            raise NotFound()
        return HttpResponseRedirect(get_storage().presigned_get(profile.signatory_image, 300))


# --- Feature flags (tenant view) ----------------------------------------------------------------


class TenantFeaturesView(APIView):
    permission_classes = [StaffReadsOrHasPermission]

    @extend_schema(
        responses=s.TenantFeatureSerializer(many=True),
        operation_id="settings_features",
        tags=["settings"],
    )
    def get(self, request: Request) -> Response:
        enabled = effective_features()
        rows = [
            {
                "code": f.code,
                "name": f.name,
                "description": f.description,
                "enabled": enabled.get(f.code, False),
                "tenant_toggleable": f.tenant_toggleable,
            }
            for f in FeatureFlag.objects.order_by("code")
        ]
        return Response(s.TenantFeatureSerializer(rows, many=True).data)


class TenantFeatureToggleView(APIView):
    permission_classes = [HasPermission]
    required_permission = "settings.manage"

    @extend_schema(
        request=FeatureToggleSerializer,
        responses=s.TenantFeatureSerializer,
        operation_id="settings_feature_toggle",
        tags=["settings"],
    )
    def put(self, request: Request, code: str) -> Response:
        data = FeatureToggleSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        enabled = tenant_settings_services.toggle_feature(
            code, data.validated_data["enabled"], by=_user(request)
        )
        flag = FeatureFlag.objects.get(code=code)
        body = {
            "code": flag.code,
            "name": flag.name,
            "description": flag.description,
            "enabled": enabled,  # the cache is refreshed only after commit
            "tenant_toggleable": flag.tenant_toggleable,
        }
        return Response(s.TenantFeatureSerializer(body).data)


# --- Tenant audit log (spec 5.16) ---------------------------------------------------------------


class TenantAuditLogView(generics.ListAPIView[AuditLog]):
    permission_classes = [HasPermission]
    required_permission = "audit.view"
    serializer_class = AuditLogSerializer

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):
            return AuditLog.objects.none()
        filters = AuditFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        f = dict(filters.validated_data)
        f.pop("tenant_id", None)  # always the caller's own tenant
        return audit_selectors.tenant_audit_logs(f)  # type: ignore[arg-type]

    @extend_schema(
        parameters=[AuditFilterSerializer], operation_id="audit_logs_list", tags=["settings"]
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


# --- Public (pre-login) branding ----------------------------------------------------------------


class PublicBrandingView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(
        responses=s.PublicBrandingSerializer, operation_id="public_tenant_branding", tags=["public"]
    )
    def get(self, request: Request, slug: str) -> Response:
        body = public_branding(slug)
        if body is None:
            raise NotFound()
        return Response(s.PublicBrandingSerializer({**body, **_sign_in_languages(body)}).data)


def _sign_in_languages(branding: dict[str, Any]) -> dict[str, Any]:
    """What a sign-in page may offer (ADR-060): the languages this distributor's people may
    choose, and its default for shops. From the settings cache rather than the branding one, so
    a change shows at once."""
    from apps.platform.selectors import get_setting
    from common import languages

    allowed = languages.available(tenant_slug=branding["slug"])
    default = get_setting("retailers.default_language", UUID(branding["tenant_id"]))
    return {
        "languages": [
            {"code": row.code, "name": row.name, "native": row.native}
            for row in languages.all_languages()
            if row.code in allowed
        ],
        "default_language": languages.effective(str(default), allowed),
    }


class PublicLanguagesView(APIView):
    """Every language the app has, and whether it is enabled for everyone (ADR-060). For the
    super admin's sign-in page, where only super admins sign in (they may use any language)."""

    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(
        responses=s.PlatformLanguageSerializer(many=True),
        operation_id="public_languages",
        tags=["public"],
    )
    def get(self, request: Request) -> Response:
        from common import languages

        on = set(languages.enabled())
        rows = [
            {"code": row.code, "name": row.name, "native": row.native, "enabled": row.code in on}
            for row in languages.all_languages()
        ]
        return Response(s.PlatformLanguageSerializer(rows, many=True).data)


class PublicAssetView(APIView):
    """Stable URL for a brand image that redirects to a short-lived link (ADR-027)."""

    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(
        responses={302: OpenApiResponse(description="Redirect to a short-lived download link")},
        operation_id="public_tenant_asset",
        tags=["public"],
    )
    def get(self, request: Request, slug: str, kind: str) -> HttpResponseRedirect:
        if kind not in tenant_settings_services.BRAND_ASSETS:  # never the signatory
            raise NotFound()
        tenant = tenant_by_slug(slug)
        if tenant is None:
            raise NotFound()
        with tenant_context(tenant.pk):
            branding = TenantBranding.objects.first()
        key = getattr(branding, kind, "") if branding else ""
        if not key:
            raise NotFound()
        response = HttpResponseRedirect(get_storage().presigned_get(key, 3600))
        response["Cache-Control"] = "public, max-age=300"
        return response
