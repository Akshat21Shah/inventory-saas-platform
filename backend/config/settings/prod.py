from django.core.exceptions import ImproperlyConfigured

from .base import *

DEBUG = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"  # SES adapter arrives in Phase 6

# Fail fast on weak keys: HS256 needs >= 32 bytes (RFC 7518 §3.2).
if len(SIMPLE_JWT["SIGNING_KEY"].encode()) < 32 or len(SECRET_KEY.encode()) < 32:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY and JWT_SIGNING_KEY must be at least 32 bytes")
