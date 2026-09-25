from django.contrib import admin

from apps.audit.models import AuditLog
from common.admin_site import ReadOnlyPlatformAdmin


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyPlatformAdmin):
    list_display = ("created_at", "tenant", "action", "actor", "impersonator", "target_repr")
    list_filter = ("action",)
    search_fields = ("action", "target_id", "target_repr")
