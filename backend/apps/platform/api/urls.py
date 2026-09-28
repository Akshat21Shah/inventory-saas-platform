from django.urls import path

from apps.platform.api import views as v

urlpatterns = [
    path("tenants/", v.TenantListCreateView.as_view(), name="platform-tenants"),
    path(
        "tenants/slug-available/", v.SlugAvailabilityView.as_view(), name="platform-slug-available"
    ),
    path("tenants/<uuid:tenant_id>/", v.TenantDetailView.as_view(), name="platform-tenant-detail"),
    path(
        "tenants/<uuid:tenant_id>/gst-identity/",
        v.TenantGstIdentityView.as_view(),
        name="platform-tenant-gst-identity",
    ),
    path(
        "tenants/<uuid:tenant_id>/suspend/",
        v.TenantSuspendView.as_view(),
        name="platform-tenant-suspend",
    ),
    path(
        "tenants/<uuid:tenant_id>/reactivate/",
        v.TenantReactivateView.as_view(),
        name="platform-tenant-reactivate",
    ),
    path(
        "tenants/<uuid:tenant_id>/features/",
        v.TenantFeaturesView.as_view(),
        name="platform-tenant-features",
    ),
    path(
        "tenants/<uuid:tenant_id>/features/<slug:code>/",
        v.TenantFeatureToggleView.as_view(),
        name="platform-tenant-feature",
    ),
    path(
        "tenants/<uuid:tenant_id>/subscription/",
        v.TenantSubscriptionView.as_view(),
        name="platform-tenant-subscription",
    ),
    path(
        "tenants/<uuid:tenant_id>/users/", v.TenantUsersView.as_view(), name="platform-tenant-users"
    ),
    path(
        "tenants/<uuid:tenant_id>/owner/resend-invite/",
        v.TenantOwnerResendView.as_view(),
        name="platform-tenant-owner-resend",
    ),
    path("dashboard/", v.DashboardView.as_view(), name="platform-dashboard"),
    path("plans/", v.PlanListCreateView.as_view(), name="platform-plans"),
    path("plans/<uuid:plan_id>/", v.PlanDetailView.as_view(), name="platform-plan-detail"),
    path("feature-flags/", v.FeatureFlagListView.as_view(), name="platform-feature-flags"),
    path(
        "feature-flags/<slug:code>/",
        v.FeatureFlagDetailView.as_view(),
        name="platform-feature-flag-detail",
    ),
    path("tax-rates/", v.TaxRateListCreateView.as_view(), name="platform-tax-rates"),
    path(
        "tax-rates/<uuid:tax_rate_id>/",
        v.TaxRateDetailView.as_view(),
        name="platform-tax-rate-detail",
    ),
    path("cess-types/", v.CessTypeListCreateView.as_view(), name="platform-cess-types"),
    path(
        "cess-types/<uuid:cess_id>/",
        v.CessTypeDetailView.as_view(),
        name="platform-cess-type-detail",
    ),
    path("hsn-rate-hints/", v.HsnHintListCreateView.as_view(), name="platform-hsn-hints"),
    path("hsn-rate-hints/import/", v.HsnHintImportView.as_view(), name="platform-hsn-hints-import"),
    path(
        "hsn-rate-hints/<uuid:hint_id>/",
        v.HsnHintDetailView.as_view(),
        name="platform-hsn-hint-detail",
    ),
    path(
        "settings/registry/",
        v.PlatformSettingsRegistryView.as_view(),
        name="platform-settings-registry",
    ),
    path(
        "settings/values/",
        v.PlatformSettingsValuesView.as_view(),
        name="platform-settings-values",
    ),
    path("audit-logs/", v.PlatformAuditLogView.as_view(), name="platform-audit-logs"),
    path(
        "impersonations/", v.ImpersonationListCreateView.as_view(), name="platform-impersonations"
    ),
]
