from django.contrib import admin

from apps.platform.models import Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("name", "slug", "status", "created_at")
    search_fields = ("name", "slug")
