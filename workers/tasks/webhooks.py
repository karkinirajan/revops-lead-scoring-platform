"""
Celery tasks for async webhook delivery and retry processing.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import structlog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

from workers.celery_app import app as celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="workers.tasks.webhooks.deliver_webhook",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    queue="sync",
)
def deliver_webhook(self, delivery_log_id: str) -> dict:
    """
    Deliver a single webhook event. Retries with exponential backoff on failure.
    delivery_log_id references the webhook_delivery_logs row.
    """
    from app.database import SessionLocal
    from app.models.webhook import WebhookDeliveryLog, WebhookDeliveryStatus, Webhook
    from app.services.webhook_service import _deliver_sync, RETRY_DELAYS

    db = SessionLocal()
    try:
        log_entry = db.get(WebhookDeliveryLog, delivery_log_id)
        if not log_entry:
            logger.warning("webhook_delivery_log_not_found", id=delivery_log_id)
            return {"status": "not_found"}

        if log_entry.status == WebhookDeliveryStatus.SUCCESS:
            return {"status": "already_delivered"}

        hook = db.get(Webhook, log_entry.webhook_id)
        if not hook:
            log_entry.status = WebhookDeliveryStatus.FAILED
            log_entry.error_message = "Webhook endpoint deleted"
            db.commit()
            return {"status": "webhook_deleted"}

        payload_bytes = json.dumps(log_entry.payload, sort_keys=True).encode()
        log_entry.attempt_number = self.request.retries + 1

        _deliver_sync(hook, log_entry, payload_bytes)
        db.commit()

        if log_entry.status == WebhookDeliveryStatus.FAILED:
            retry_num = self.request.retries
            if retry_num < len(RETRY_DELAYS):
                delay = RETRY_DELAYS[retry_num]
                logger.info("webhook_retrying", delivery_id=delivery_log_id, delay=delay, attempt=retry_num + 1)
                raise self.retry(countdown=delay)

        return {"status": log_entry.status, "http_status": log_entry.http_status_code}

    finally:
        db.close()


@celery_app.task(
    name="workers.tasks.webhooks.retry_failed_webhooks",
    queue="sync",
)
def retry_failed_webhooks() -> dict:
    """
    Periodic task: find failed deliveries eligible for retry and re-queue them.
    Runs every 30 minutes via beat schedule.
    """
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models.webhook import WebhookDeliveryLog, WebhookDeliveryStatus
    from app.services.webhook_service import MAX_ATTEMPTS
    from datetime import timedelta

    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        failed = db.scalars(
            select(WebhookDeliveryLog)
            .where(
                WebhookDeliveryLog.status == WebhookDeliveryStatus.FAILED,
                WebhookDeliveryLog.attempt_number < MAX_ATTEMPTS,
                WebhookDeliveryLog.created_at >= cutoff,
            )
            .limit(100)
        ).all()

        queued = 0
        for entry in failed:
            deliver_webhook.apply_async(kwargs={"delivery_log_id": entry.id}, queue="sync")
            queued += 1

        logger.info("webhook_retry_sweep", queued=queued)
        return {"queued": queued}
    finally:
        db.close()
