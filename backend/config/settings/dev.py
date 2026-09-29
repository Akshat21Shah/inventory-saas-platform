import re

from .base import *

DEBUG = True
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=1025)
AUTH_COOKIE_SECURE = env.bool("AUTH_COOKIE_SECURE", default=False)  # dev runs over plain http
WEB_URL_TEMPLATE = env("WEB_URL_TEMPLATE", default="http://{host}:3000")
ALLOW_MOCK_INTEGRATIONS = env.bool("ALLOW_MOCK_INTEGRATIONS", default=True)
OTP_FIXED_CODE = env("OTP_FIXED_CODE", default="123456")  # mock SMS: sign in with 123456
# Read what the mock WhatsApp and SMS providers "send" in Mailpit (http://localhost:8025).
MOCK_MESSAGES_TO_MAILPIT = env.bool("MOCK_MESSAGES_TO_MAILPIT", default=True)
# Host-run web server (npm run dev on the host) reaches Django from localhost; Compose sets the
# web container's fixed address instead.
TRUSTED_PROXIES = env.list("TRUSTED_PROXIES", default=["127.0.0.1", "::1"])
# Browsers on any subdomain of the dev platform domain (*.localhost, or <lan-ip>.nip.io after
# "make lan"). Dev only: base.py and prod.py are unchanged.
CORS_ALLOWED_ORIGIN_REGEXES = env.list(
    "CORS_ALLOWED_ORIGIN_REGEXES",
    default=[rf"^https?://([a-z0-9-]+\.)?{re.escape(PLATFORM_DOMAIN)}(:\d+)?$"],
)
