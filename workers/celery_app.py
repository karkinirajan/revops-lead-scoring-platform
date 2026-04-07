"""
Celery application — queue definitions, routing, and shared configuration.

Queues:
  ingest    — raw event normalization and deduplication
  features  — incremental feature aggregation
  scoring   — lead scoring execution
  sync      — outbound CRM upserts
  dlq       — dead-letter reprocessing
"""
import os
import sys

# Make the API app importable from workers
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

from celery import Celery
from celery.utils.log import get_task_logger
from kombu import Exchange, Queue

BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

app = Celery("revops", broker=BROKER_URL, backend=RESULT_BACKEND)

# ---- Queue / Exchange definitions ----
default_exchange = Exchange("revops", type="direct")

app.conf.task_queues = [
    Queue("ingest", default_exchange, routing_key="ingest"),
    Queue("features", default_exchange, routing_key="features"),
    Queue("scoring", default_exchange, routing_key="scoring"),
    Queue("sync", default_exchange, routing_key="sync"),
    Queue("dlq", default_exchange, routing_key="dlq"),
]

app.conf.task_default_queue = "ingest"
app.conf.task_default_exchange = "revops"
app.conf.task_default_routing_key = "ingest"

# ---- Task routing ----
app.conf.task_routes = {
    "workers.tasks.ingest.*": {"queue": "ingest"},
    "workers.tasks.features.*": {"queue": "features"},
    "workers.tasks.scoring.*": {"queue": "scoring"},
    "workers.tasks.sync.*": {"queue": "sync"},
    "workers.tasks.dlq.*": {"queue": "dlq"},
}

# ---- Retry and reliability ----
app.conf.task_acks_late = True                    # ack only after successful completion
app.conf.task_reject_on_worker_lost = True        # re-queue on worker crash
app.conf.task_serializer = "json"
app.conf.result_serializer = "json"
app.conf.accept_content = ["json"]
app.conf.timezone = "UTC"
app.conf.enable_utc = True

# ---- Worker limits ----
app.conf.worker_prefetch_multiplier = 1           # fair dispatch, prevents queue hoarding
app.conf.task_soft_time_limit = int(os.environ.get("CELERY_TASK_SOFT_TIME_LIMIT", 300))
app.conf.task_time_limit = int(os.environ.get("CELERY_TASK_TIME_LIMIT", 600))

# ---- Beat schedule (periodic tasks) ----
app.conf.beat_schedule = {
    "hourly-feature-recompute": {
        "task": "workers.tasks.features.recompute_all_features",
        "schedule": 3600.0,  # every hour
        "options": {"queue": "features"},
    },
    "hourly-scoring-run": {
        "task": "workers.tasks.scoring.run_scoring_batch",
        "schedule": 3600.0,
        "kwargs": {"filter_segment": None, "is_shadow": False},
        "options": {"queue": "scoring"},
    },
    "daily-hubspot-sync": {
        "task": "workers.tasks.sync.sync_top_leads_to_hubspot",
        "schedule": 86400.0,  # every 24h
        "options": {"queue": "sync"},
    },
    "dlq-reprocessor": {
        "task": "workers.tasks.dlq.reprocess_dlq",
        "schedule": 1800.0,  # every 30 min
        "options": {"queue": "dlq"},
    },
}

# Auto-discover tasks
app.autodiscover_tasks(["workers.tasks"])
