from django.contrib import admin

from apps.accounts.models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("email", "phone", "user_type", "is_active", "created_at")
    search_fields = ("email", "phone", "full_name")
    list_filter = ("user_type", "is_active")
