"""Celery application. Tasks that touch tenant data subclass `common.task_base.TenantTask`."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("inventory")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
app.autodiscover_tasks(["common"], related_name="outbox")
app.autodiscover_tasks(["common"], related_name="idempotency")
