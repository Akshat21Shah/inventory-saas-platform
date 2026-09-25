# Backend image (API, Celery worker, Celery beat). Build context: backend/
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH
RUN pip install --no-cache-dir uv==0.12.18 \
    && useradd --create-home --uid 1000 app
WORKDIR /app

FROM base AS dev
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project
COPY . .
USER app
EXPOSE 8000
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS prod
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY . .
# Build-time-only values so prod settings load for collectstatic; runtime values come from the env.
RUN DJANGO_SECRET_KEY=build-time-only-key-for-collectstatic-0000 DATABASE_URL=postgres://x@localhost/x \
    FIELD_ENCRYPTION_KEYS=YnVpbGQtdGltZS1vbmx5LW5vdC1hLXJlYWwta2V5MDA= \
    python manage.py collectstatic --noinput --settings=config.settings.prod
USER app
EXPOSE 8000
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
