from django.apps import AppConfig


class ReportsConfig(AppConfig):
    name = "apps.reports"
    label = "reports"
    verbose_name = "Reports"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from apps.reports import definitions, tasks  # noqa: F401  (reports register; tasks by name)
