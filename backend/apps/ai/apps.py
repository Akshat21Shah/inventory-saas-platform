from django.apps import AppConfig


class AiConfig(AppConfig):
    name = "apps.ai"
    label = "ai"
    verbose_name = "AI features"
    default_auto_field = "django.db.models.BigAutoField"
