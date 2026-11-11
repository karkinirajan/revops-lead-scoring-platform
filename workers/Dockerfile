# syntax=docker/dockerfile:1
# The Celery worker / beat image. Build it from the repository root:
#   docker build -f workers/Dockerfile --target production -t revops-worker .
FROM python:3.14-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
RUN pip install --no-cache-dir uv==0.13.7

# ---- Dependencies (the workers depend on the API package and the ML extra) ----
FROM base AS deps
COPY pyproject.toml uv.lock .python-version ./
COPY apps/api/pyproject.toml apps/api/README.md apps/api/
COPY workers/pyproject.toml workers/
RUN uv sync --frozen --no-dev --no-install-workspace --package revops-workers

# ---- Development: the source is mounted over /app/apps/api and /app/workers by docker-compose ----
FROM deps AS development
COPY apps/api apps/api
COPY workers workers
RUN uv sync --frozen --package revops-workers
CMD ["celery", "-A", "workers.celery_app", "worker", "--loglevel=info", "--concurrency=4", "-Q", "ingest,features,scoring,sync,dlq"]

# ---- Build ----
FROM deps AS build
COPY apps/api apps/api
RUN uv sync --frozen --no-dev --no-editable --package revops-workers

# ---- Production ----
FROM base AS production
RUN useradd --create-home --uid 1001 appuser
COPY --from=build --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser workers workers
USER appuser
CMD ["celery", "-A", "workers.celery_app", "worker", "--loglevel=warning", "--concurrency=8", "-Q", "ingest,features,scoring,sync,dlq"]
