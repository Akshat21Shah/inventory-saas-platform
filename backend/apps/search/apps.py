from django.apps import AppConfig


class SearchConfig(AppConfig):
    name = "apps.search"
    label = "search"
    verbose_name = "Search"
    default_auto_field = "django.db.models.BigAutoField"
