"""Base settings shared by every environment. Values come from the environment (12-factor)."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import environ

BASE_DIR = Path(__file__).resolve().parents[2]  # backend/
REPO_DIR = BASE_DIR.parent

env = environ.Env()
if (REPO_DIR / ".env").exists():
    environ.Env.read_env(REPO_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)

# Host routing (ADR-019, ADR-020): admin.<domain>, {slug}.<domain>, <domain>.
PLATFORM_DOMAIN: str = env("PLATFORM_DOMAIN", default="localhost")
ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS", default=[PLATFORM_DOMAIN, f".{PLATFORM_DOMAIN}", "backend"]
)
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "channels",
    "common",
    "apps.platform",
    "apps.accounts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "common.middleware.RequestContextMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database (ADR-002) -------------------------------------------------------------------------
# DATABASE_URL: runtime role WITHOUT BYPASSRLS (app_user). Migrations run with the owner role by
# pointing DATABASE_URL at app_owner (see `make migrate`).
# PLATFORM_DATABASE_URL: BYPASSRLS role, reachable only through audited platform services.
DATABASES = {
    "default": {
        **env.db("DATABASE_URL"),
        "ATOMIC_REQUESTS": True,  # one transaction per request: required for SET LOCAL tenant (RLS)
        "CONN_MAX_AGE": env.int("DB_CONN_MAX_AGE", default=60),
        "CONN_HEALTH_CHECKS": True,
    },
}
if env("PLATFORM_DATABASE_URL", default=""):
    DATABASES["platform"] = {
        **env.db("PLATFORM_DATABASE_URL"),
        "ATOMIC_REQUESTS": False,
        "CONN_MAX_AGE": env.int("DB_CONN_MAX_AGE", default=60),
        "TEST": {"MIRROR": "default"},
    }
DATABASE_ROUTERS = ["common.db_router.PlatformAliasRouter"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Time & locale: store UTC, display Asia/Kolkata ---------------------------------------------
LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
DISPLAY_TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Cache / Redis / Celery / Channels ---------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "inv",
    }
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = None
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 240
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULE = {
    "outbox-sweeper": {"task": "common.outbox.sweep_outbox", "schedule": 60.0},
    "idempotency-purge": {"task": "common.idempotency.purge_expired", "schedule": 3600.0},
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

# --- DRF / OpenAPI / JWT ---------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["common.authentication.TenantJWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "common.pagination.DefaultCursorPagination",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "common.exceptions.api_exception_handler",
    "COERCE_DECIMAL_TO_STRING": True,  # money travels as strings, never floats
    "DEFAULT_THROTTLE_RATES": {"anon": "60/min", "user": "600/min"},
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Inventory Platform API",
    "DESCRIPTION": (
        "Multi-tenant B2B inventory & ordering platform. All money values are decimal strings."
    ),
    "VERSION": "1.0.0",
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,
    "SERVE_INCLUDE_SCHEMA": False,
    "ENUM_NAME_OVERRIDES": {},
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(seconds=env.int("JWT_ACCESS_LIFETIME_SECONDS", default=600)),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        seconds=env.int("JWT_REFRESH_LIFETIME_SECONDS", default=7 * 24 * 3600)
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "SIGNING_KEY": env("JWT_SIGNING_KEY", default=SECRET_KEY),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_CLAIM": "sub",
}

CORS_ALLOWED_ORIGIN_REGEXES = env.list(
    "CORS_ALLOWED_ORIGIN_REGEXES", default=[r"^https?://([a-z0-9-]+\.)?localhost(:\d+)?$"]
)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "idempotency-key",
    "x-request-id",
]

# --- Logging: structured JSON with request/tenant context --------------------------------------
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOGGING: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"context": {"()": "common.logging.RequestContextFilter"}},
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s",
            "rename_fields": {"asctime": "ts", "levelname": "level", "name": "logger"},
        },
        "console": {
            "format": "%(levelname)s %(name)s [%(request_id)s t=%(tenant_id)s] %(message)s"
        },
    },
    "handlers": {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": env("LOG_FORMAT", default="json"),
            "filters": ["context"],
        }
    },
    "root": {"handlers": ["default"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        "celery": {"level": LOG_LEVEL},
    },
}

# --- Sentry ------------------------------------------------------------------------------------
SENTRY_DSN = env("SENTRY_DSN", default="")
ENVIRONMENT = env("ENVIRONMENT", default="local")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=ENVIRONMENT,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.0),
        send_default_pii=False,
    )

# --- App settings --------------------------------------------------------------------------------
IDEMPOTENCY_TTL_SECONDS = 24 * 3600
OUTBOX_SWEEP_AFTER_SECONDS = 60
