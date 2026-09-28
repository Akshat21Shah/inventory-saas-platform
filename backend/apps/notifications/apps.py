from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = "apps.notifications"
    label = "notifications"
    verbose_name = "Notifications"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from apps.notifications import checks, tasks  # noqa: F401  (deploy checks; tasks by name)
        from apps.notifications.consumer import HANDLED_EVENTS
        from common.outbox import register_handler

        for event_type in HANDLED_EVENTS:
            register_handler(event_type, "notifications.dispatch_event")
