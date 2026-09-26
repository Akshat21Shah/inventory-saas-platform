from django.apps import AppConfig


class DataioConfig(AppConfig):
    name = "apps.dataio"
    label = "dataio"
    verbose_name = "Data import and export"
    default_auto_field = "django.db.models.BigAutoField"
