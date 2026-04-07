FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Install API deps (workers share the same Python deps)
COPY ../apps/api/pyproject.toml /app/api/pyproject.toml
RUN pip install -e /app/api

# Install worker-specific deps
COPY pyproject.toml /app/workers/pyproject.toml
RUN pip install -e /app/workers

FROM base AS development
COPY . /app/workers
COPY ../apps/api /app/api
CMD ["celery", "-A", "workers.celery_app", "worker", "--loglevel=info", "--concurrency=4", "-Q", "ingest,features,scoring,sync,dlq"]

FROM base AS production
COPY . /app/workers
COPY ../apps/api /app/api
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app
USER appuser
CMD ["celery", "-A", "workers.celery_app", "worker", "--loglevel=info", "--concurrency=8", "-Q", "ingest,features,scoring,sync,dlq"]
