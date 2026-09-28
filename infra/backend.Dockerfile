# Backend image (API, Celery worker, Celery beat). Build context: backend/
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH
# PDFs (ADR-046): WeasyPrint's libraries and Noto Sans, which has the rupee sign.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.12.18 \
    && useradd --create-home --uid 1000 app
WORKDIR /app

FROM base AS dev
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project
COPY . .
USER app
EXPOSE 8000
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--reload", "--no-proxy-headers"]

FROM base AS prod
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY . .
# Build-time-only values so prod settings load for collectstatic; runtime values come from the env.
RUN DJANGO_SECRET_KEY=build-time-only-key-for-collectstatic-0000 DATABASE_URL=postgres://x@localhost/x \
    FIELD_ENCRYPTION_KEYS=YnVpbGQtdGltZS1vbmx5LW5vdC1hLXJlYWwta2V5MDA= \
    python manage.py collectstatic --noinput --settings=config.settings.prod
USER app
# Without this, manage.py/asgi.py fall back to dev settings (DEBUG on).
ENV DJANGO_SETTINGS_MODULE=config.settings.prod
EXPOSE 8000
# Startup gate: deployment checks with database access must pass before serving (mock SMS,
# fixed OTP, the public dev 2FA key: accounts.E001-E003); warnings do not block.
# No --proxy-headers: Django's TrustedProxyMiddleware decides which forwarded headers to trust.
CMD ["sh", "-c", "python manage.py check --deploy --database default --fail-level ERROR && exec uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --no-proxy-headers"]
