from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Accounts"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from apps.accounts import (  # noqa: F401  (register check and OpenAPI extension)
            checks,
            schema,
        )
