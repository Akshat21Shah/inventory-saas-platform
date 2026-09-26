from django.apps import AppConfig


class BillingConfig(AppConfig):
    name = "apps.billing"
    label = "billing"
    verbose_name = "Billing"
    default_auto_field = "django.db.models.BigAutoField"
