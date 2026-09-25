from django.apps import AppConfig


class TestAppConfig(AppConfig):
    name = "common.tests.testapp"
    label = "testapp"
    default_auto_field = "django.db.models.BigAutoField"
