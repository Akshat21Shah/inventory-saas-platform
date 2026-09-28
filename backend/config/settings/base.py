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
# Addresses (IPs or CIDRs) of the proxies allowed to set X-Forwarded-* headers: the Next.js
# server(s) in every environment (ADR-032). Forwarded headers from anyone else are discarded.
TRUSTED_PROXIES: list[str] = env.list("TRUSTED_PROXIES", default=[])

INSTALLED_APPS = [
    "common.admin_apps.PlatformAdminConfig",  # django.contrib.admin, locked down (PLAN 1.13)
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "channels",
    "common",
    "apps.platform",
    "apps.accounts",
    "apps.audit",
    "apps.retailers",
    "apps.catalog",
    "apps.pricing",
    "apps.inventory",
    "apps.ledger",
    "apps.orders",
    "apps.billing",
    "apps.payments",
    "apps.dataio",
    "apps.shop",
]

MIDDLEWARE = [
    "common.net.TrustedProxyMiddleware",  # first: forwarded headers only from trusted proxies
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "common.middleware.RequestContextMiddleware",
    "apps.accounts.middleware.ImpersonationAuditMiddleware",
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
    "login-records-purge": {"task": "accounts.purge_expired_login_records", "schedule": 3600.0},
    "impersonation-expiry": {"task": "accounts.expire_impersonation_sessions", "schedule": 60.0},
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

# --- DRF / OpenAPI / JWT ---------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.SessionJWTAuthentication"],
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
    "ENUM_NAME_OVERRIDES": {
        "TenantStatusEnum": "apps.platform.models.Tenant.Status",
        "InvitationStatusEnum": "apps.accounts.models.Invitation.Status",
        "UserTypeEnum": "apps.accounts.models.User.UserType",
        "ImportModeEnum": "apps.dataio.models.ImportJob.Mode",
        "CopyModeEnum": "apps.pricing.tools.COPY_MODE_CHOICES",
        "ReceiptStatusEnum": "apps.inventory.models.StockInward.Status",
        "StockAlertStatusEnum": "apps.inventory.models.StockAlert.Status",
        "StockAlertTypeEnum": "apps.inventory.models.StockAlert.Type",
        "AdjustmentModeEnum": "apps.inventory.models.StockAdjustmentLine.Mode",
        "StockStatusEnum": "apps.inventory.selectors.STOCK_STATUS_CHOICES",
        "ShopAvailabilityLabelEnum": "apps.inventory.availability.LABELS",
        "ImportStatusEnum": "apps.dataio.models.ImportJob.Status",
        "ImportKindEnum": "apps.dataio.models.ImportJob.Kind",
        "AddressKindEnum": "apps.retailers.models.RetailerAddress.Kind",
        "RetailerStatusEnum": "apps.retailers.models.Retailer.Status",
        "PreferredLanguageEnum": "apps.accounts.models.LANGUAGE_CHOICES",
        "OrderStatusEnum": "apps.orders.models.OrderStatus",
        "FulfilmentStatusEnum": "apps.orders.models.Fulfilment.Status",
        "FulfilmentKindEnum": "apps.orders.models.Fulfilment.Kind",
        "AllocationStatusEnum": "apps.orders.models.BackorderAllocation.Status",
        "AllocationTriggerEnum": "apps.orders.models.BackorderAllocation.Trigger",
        "PriceSourceEnum": ["SPECIAL", "PRICE_LIST", "BASE"],
        "ShipmentPriceSourceEnum": "apps.orders.models.FulfilmentLine.PriceSource",
        "AuditLogActorTypeEnum": "apps.audit.models.AuditLog.ActorType",
        "HistoryActorTypeEnum": "apps.orders.models.OrderStatusHistory.ActorType",
        "HoldReasonEnum": "apps.orders.models.Order.HoldReason",
        "InvoicePaymentStatusEnum": "apps.billing.models.PaymentStatus",
        "PdfStatusEnum": "apps.billing.models.PdfStatus",
        "EInvoiceStatusEnum": "apps.billing.models.EInvoiceStatus",
        "InvoiceTriggerEnum": "apps.billing.models.Invoice.Trigger",
        "CreditNoteKindEnum": "apps.billing.models.CreditNote.Kind",
        "CreditNoteCreateKindEnum": ["RETURN", "PRICE_ADJUSTMENT"],
        "ReturnReasonEnum": "apps.billing.models.CreditNote.ReturnReason",
        "DispositionEnum": "apps.billing.models.CreditNoteLine.Disposition",
        "LedgerAdjustmentKindEnum": "apps.ledger.models.LedgerAdjustment.Kind",
        "EntryTypeEnum": "apps.ledger.models.EntryType",
        "PaymentModeEnum": "apps.payments.models.Payment.Mode",
        "PaymentStatusEnum": "apps.payments.models.Payment.Status",
        "CreditTimingEnum": "apps.payments.models.Payment.CreditTiming",
        "HandoverStatusEnum": "apps.payments.models.Payment.Handover",
        "DueTypeEnum": ["INVOICE", "ADJUSTMENT"],
        "MoneySourceTypeEnum": ["PAYMENT", "CREDIT_NOTE", "ADJUSTMENT"],
        "LedgerReferenceTypeEnum": ["INVOICE", "CREDIT_NOTE", "PAYMENT", "ADJUSTMENT", "REFUND"],
        "AllocationTargetTypeEnum": ["INVOICE", "ADJUSTMENT", "REFUND"],
        "RefundModeEnum": "apps.payments.models.Refund.Mode",
        "AgeingBasisEnum": ["INVOICE_DATE", "DUE_DATE"],
        "LoginStatusEnum": [
            "authenticated",
            "handoff",
            "choose_tenant",
            "choose_account",
            "mfa_required",
            "mfa_setup_required",
        ],
    },
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
    # Tokens carry a hash of the password: changing or resetting it revokes every token at once.
    "CHECK_REVOKE_TOKEN": True,
}

# --- Auth sessions (ADR-025) ---------------------------------------------------------------------
# Refresh lifetime per user type. Retailer sessions slide (each rotation restarts the window);
# staff and super admin sessions end at a fixed time after sign-in.
AUTH_REFRESH_LIFETIMES = {
    "RETAILER": timedelta(days=30),
    "STAFF": timedelta(days=7),
    "PLATFORM": timedelta(hours=12),
}
AUTH_SLIDING_USER_TYPES = frozenset({"RETAILER"})
AUTH_REFRESH_COOKIE_NAME = "rt"
AUTH_REFRESH_COOKIE_PATH = "/api/v1/auth/"
AUTH_COOKIE_SECURE = env.bool("AUTH_COOKIE_SECURE", default=True)
AUTH_HANDOFF_TTL_SECONDS = 60
AUTH_CHALLENGE_TTL_SECONDS = 300
TENANT_STATUS_CACHE_SECONDS = 30
# Invalidated on every change; the TTL only bounds a missed invalidation.
PUBLIC_BRANDING_CACHE_SECONDS = 600
TOTP_ISSUER = env("TOTP_ISSUER", default="Inventory Platform")
OTP_TTL_SECONDS = 300
INVITATION_TTL_DAYS = 7
OTP_RESEND_AFTER_SECONDS = 30

# --- Integrations (CLAUDE.md §4: adapters with mock implementations) -----------------------------
# Mock adapters are refused unless explicitly allowed (dev/test); `manage.py check --deploy` fails
# when a mock is configured without the allowance.
ALLOW_MOCK_INTEGRATIONS = env.bool("ALLOW_MOCK_INTEGRATIONS", default=False)
SMS_PROVIDER = env("SMS_PROVIDER", default="mock")
# Object storage (ADR-027): "s3" (AWS in prod, SeaweedFS in dev) or "memory" (tests).
STORAGE_BACKEND = env("STORAGE_BACKEND", default="s3")
S3_ENDPOINT_URL = env("S3_ENDPOINT_URL", default="")  # empty = AWS
S3_PUBLIC_ENDPOINT_URL = env("S3_PUBLIC_ENDPOINT_URL", default="")  # what browsers reach
S3_BUCKET = env("S3_BUCKET", default="inventory-dev")
# Anonymous read, no listing (ADR-034); served through the CDN in production.
S3_PUBLIC_BUCKET = env("S3_PUBLIC_BUCKET", default="inventory-public-dev")
PUBLIC_ASSETS_BASE_URL = env("PUBLIC_ASSETS_BASE_URL", default="")  # empty = S3 public endpoint
# Invoices, credit notes, receipts, order confirmations (ADR-046): "weasyprint" or "fake" (tests).
PDF_RENDERER = env("PDF_RENDERER", default="weasyprint")
S3_ACCESS_KEY = env("S3_ACCESS_KEY", default="")
S3_SECRET_KEY = env("S3_SECRET_KEY", default="")
S3_REGION = env("S3_REGION", default="ap-south-1")
# Dev only: every OTP is this code (honoured only with ALLOW_MOCK_INTEGRATIONS).
OTP_FIXED_CODE: str | None = env("OTP_FIXED_CODE", default=None)
# Links in emails point at the web app: "{host}" is e.g. "admin.<domain>" or "<slug>.<domain>".
WEB_URL_TEMPLATE = env("WEB_URL_TEMPLATE", default="https://{host}")

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

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Inventory Platform <no-reply@localhost>")

# --- App settings --------------------------------------------------------------------------------
IDEMPOTENCY_TTL_SECONDS = 24 * 3600
OUTBOX_SWEEP_AFTER_SECONDS = 60

# --- Field-level encryption (ADR-031) ------------------------------------------------------------
# Comma-separated Fernet keys: the first encrypts, all decrypt (rotation). Prod refuses the dev key,
# which is base64("dev-only-insecure-fernet-key-000").
DEV_FIELD_ENCRYPTION_KEY = "ZGV2LW9ubHktaW5zZWN1cmUtZmVybmV0LWtleS0wMDA="
FIELD_ENCRYPTION_KEYS: list[str] = env.list("FIELD_ENCRYPTION_KEYS", default=[]) or [
    DEV_FIELD_ENCRYPTION_KEY
]

# --- Plans (spec 5.1): limits are defined but not enforced until this is switched on ------------
PLAN_ENFORCEMENT_ENABLED = env.bool("PLAN_ENFORCEMENT_ENABLED", default=False)
