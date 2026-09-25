import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DATABASE_URL", "postgres://app_owner:app_owner@localhost:5432/inventory")

from .base import *

DEBUG = False
INSTALLED_APPS += ["common.tests.testapp"]
# The audited platform alias (ADR-002). Locally .env points it at the BYPASSRLS role; in CI it
# reuses the default credentials. Either way it mirrors the test database (a separate connection,
# so tests reading through it must be transactional).
if "platform" not in DATABASES:
    DATABASES["platform"] = {
        **DATABASES["default"],
        "ATOMIC_REQUESTS": False,
        "TEST": {"MIRROR": "default"},
    }
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
LOGGING["handlers"]["default"]["formatter"] = "console"
LOGGING["root"]["level"] = "WARNING"
ALLOW_MOCK_INTEGRATIONS = True
OTP_FIXED_CODE = None  # tests read real random codes from the mock SMS outbox
STORAGE_BACKEND = "memory"
TRUSTED_PROXIES = ["127.0.0.1"]  # the test client plays the Next.js proxy
