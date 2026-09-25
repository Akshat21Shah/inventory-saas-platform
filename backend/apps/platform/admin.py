from django.contrib import admin

from apps.platform.models import CessType, FeatureFlag, HsnRateHint, Plan, State, TaxRate, Tenant
from common.admin_site import ReadOnlyPlatformAdmin


@admin.register(Tenant)
class TenantAdmin(ReadOnlyPlatformAdmin):
    list_display = ("name", "slug", "status", "gstin", "state", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "slug", "gstin")
    exclude = ("webhook_token",)


@admin.register(Plan)
class PlanAdmin(ReadOnlyPlatformAdmin):
    list_display = ("code", "name", "price_monthly", "is_default", "is_active")


@admin.register(FeatureFlag)
class FeatureFlagAdmin(ReadOnlyPlatformAdmin):
    list_display = ("code", "name", "default_enabled", "tenant_toggleable")


@admin.register(TaxRate)
class TaxRateAdmin(ReadOnlyPlatformAdmin):
    list_display = ("rate", "label", "is_active")


@admin.register(CessType)
class CessTypeAdmin(ReadOnlyPlatformAdmin):
    list_display = ("code", "name", "calc_method", "is_active")


@admin.register(HsnRateHint)
class HsnRateHintAdmin(ReadOnlyPlatformAdmin):
    list_display = ("hsn_prefix", "gst_rate", "effective_from", "description")
    search_fields = ("hsn_prefix",)


@admin.register(State)
class StateAdmin(ReadOnlyPlatformAdmin):
    list_display = ("code", "name", "is_union_territory", "is_active")
