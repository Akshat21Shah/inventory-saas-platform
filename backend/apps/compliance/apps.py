from django.apps import AppConfig


class ComplianceConfig(AppConfig):
    name = "apps.compliance"
    label = "compliance"
    verbose_name = "E-invoicing and e-way bills"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from apps.compliance import checks, tasks  # noqa: F401  (deploy checks; tasks by name)
