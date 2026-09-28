from django.apps import AppConfig


class LedgerConfig(AppConfig):
    name = "apps.ledger"
    label = "ledger"
    verbose_name = "Ledger"
    default_auto_field = "django.db.models.BigAutoField"
