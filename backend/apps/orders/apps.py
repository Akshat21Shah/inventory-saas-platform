from django.apps import AppConfig


class OrdersConfig(AppConfig):
    name = "apps.orders"
    label = "orders"
    verbose_name = "Orders"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from apps.orders.tasks import LIVE_EVENTS
        from common.outbox import register_handler

        for event_type in LIVE_EVENTS:
            register_handler(event_type, "orders.push_live")
