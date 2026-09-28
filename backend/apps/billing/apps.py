from django.apps import AppConfig


class BillingConfig(AppConfig):
    name = "apps.billing"
    label = "billing"
    verbose_name = "Billing"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from apps.billing.tasks import PDF_EVENTS
        from common.outbox import register_handler

        for event_type in PDF_EVENTS:
            register_handler(event_type, "billing.render_for_event")
