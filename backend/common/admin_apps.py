"""App config swapping in the locked-down admin site (kept free of model imports)."""

from django.contrib.admin.apps import AdminConfig


class PlatformAdminConfig(AdminConfig):
    default_site = "common.admin_site.PlatformAdminSite"
