# syntax=docker/dockerfile:1
# The API image. Build it from the repository root (the Python projects share one uv.lock):
#   docker build -f apps/api/Dockerfile --target production -t revops-api .
FROM python:3.14-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# curl is for the health check; psycopg2-binary carries its own libpq, so nothing needs compiling
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.13.7

# ---- Dependencies (cached until pyproject.toml / uv.lock change) ----
FROM base AS deps
COPY pyproject.toml uv.lock .python-version ./
COPY apps/api/pyproject.toml apps/api/README.md apps/api/
COPY workers/pyproject.toml workers/
RUN uv sync --frozen --no-dev --no-install-workspace --package revops-api

# ---- Development: the source is mounted over /app/apps/api by docker-compose ----
FROM deps AS development
COPY apps/api apps/api
COPY workers workers
RUN uv sync --frozen --package revops-api
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "apps/api", "--reload-dir", "workers"]

# ---- Build the application into the virtual environment ----
FROM deps AS build
COPY apps/api apps/api
RUN uv sync --frozen --no-dev --no-editable --package revops-api

# ---- Production ----
FROM base AS production
RUN useradd --create-home --uid 1001 appuser
COPY --from=build --chown=appuser:appuser /app/.venv /app/.venv
# `workers.*` is imported by the API; Alembic needs its config and migrations next to the app
COPY --chown=appuser:appuser workers workers
COPY --chown=appuser:appuser apps/api/alembic.ini apps/api/alembic.ini
COPY --chown=appuser:appuser apps/api/migrations apps/api/migrations
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD curl -fsS http://127.0.0.1:8000/health || exit 1
# Behind the reverse proxy the client address is in X-Forwarded-For; trust it only because the API is reachable through the proxy alone.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--proxy-headers", "--forwarded-allow-ips", "*"]
