from django.apps import AppConfig


class ShopConfig(AppConfig):
    """The retailer app's API (``/api/v1/shop/``, PLAN §3.9). No models of its own."""

    name = "apps.shop"
    label = "shop"
    verbose_name = "Shop"
    default_auto_field = "django.db.models.BigAutoField"
