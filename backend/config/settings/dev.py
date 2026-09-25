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
