from django.urls import path

from apps.platform.api import tenant_views as v

urlpatterns = [
    path("settings/business/", v.BusinessSettingsView.as_view(), name="settings-business"),
    path("settings/bank-details/", v.BankDetailsView.as_view(), name="settings-bank-details"),
    path("settings/registry/", v.TenantSettingsRegistryView.as_view(), name="settings-registry"),
    path("settings/values/", v.TenantSettingsValuesView.as_view(), name="settings-values"),
    path(
        "settings/values/<str:key>/",
        v.TenantSettingResetView.as_view(),
        name="settings-value-reset",
    ),
    path("settings/branding/", v.BrandingView.as_view(), name="settings-branding"),
    path(
        "settings/branding/assets/<slug:kind>/",
        v.BrandingAssetView.as_view(),
        name="settings-branding-asset",
    ),
    path(
        "settings/signatory-image/", v.SignatoryImageView.as_view(), name="settings-signatory-image"
    ),
    path("settings/features/", v.TenantFeaturesView.as_view(), name="settings-features"),
    path(
        "settings/features/<slug:code>/",
        v.TenantFeatureToggleView.as_view(),
        name="settings-feature-toggle",
    ),
    path("audit-logs/", v.TenantAuditLogView.as_view(), name="audit-logs"),
    path(
        "public/tenants/<slug:slug>/branding/",
        v.PublicBrandingView.as_view(),
        name="public-tenant-branding",
    ),
    path(
        "public/tenants/<slug:slug>/assets/<slug:kind>/",
        v.PublicAssetView.as_view(),
        name="public-tenant-asset",
    ),
]
