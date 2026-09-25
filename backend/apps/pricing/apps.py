from django.apps import AppConfig


class PricingConfig(AppConfig):
    name = "apps.pricing"
    label = "pricing"
    verbose_name = "Pricing"
    default_auto_field = "django.db.models.BigAutoField"
