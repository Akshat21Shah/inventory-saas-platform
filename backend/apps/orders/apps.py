from django.apps import AppConfig


class OrdersConfig(AppConfig):
    name = "apps.orders"
    label = "orders"
    verbose_name = "Orders"
    default_auto_field = "django.db.models.BigAutoField"
