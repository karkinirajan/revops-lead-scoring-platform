"""
Webhook delivery service.

Responsibilities:
  - Build signed payloads
  - Fire webhooks synchronously (used in tests / immediate mode)
  - Schedule async delivery via Celery (default production path)
  - Exponential backoff on failure (3 retries: 30s, 5m, 30m)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.webhook import Webhook, WebhookDeliveryLog, WebhookDeliveryStatus, WebhookEvent

logger = structlog.get_logger(__name__)

# Retry delays in seconds: attempt 1 → 30s, 2 → 300s, 3 → 1800s
RETRY_DELAYS = [30, 300, 1800]
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1  # 4 total (1 initial + 3 retries)


def _sign_payload(secret: str, payload_bytes: bytes) -> str:
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


def build_payload(event_type: str, contact_id: str | None, data: dict) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "event": event_type,
        "contact_id": contact_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


def get_active_webhooks_for_event(db: Session, event_type: str, tier: str | None = None) -> list[Webhook]:
    """Return all active webhooks subscribed to this event (and matching tier filter)."""
    hooks = db.scalars(
        select(Webhook).where(Webhook.status == "active")
    ).all()

    matching = []
    for hook in hooks:
        if event_type not in hook.event_list:
            continue
        if tier and hook.tier_filter_list and tier.upper() not in hook.tier_filter_list:
            continue
        matching.append(hook)
    return matching


def dispatch_event(
    db: Session,
    event_type: str,
    contact_id: str | None,
    data: dict,
    tier: str | None = None,
    async_mode: bool = True,
) -> int:
    """
    Fire all matching webhooks for an event.

    In async_mode (default), enqueues Celery tasks.
    In sync mode, delivers immediately (useful in tests).
    Returns the number of webhooks queued/delivered.
    """
    hooks = get_active_webhooks_for_event(db, event_type, tier)
    if not hooks:
        return 0

    payload = build_payload(event_type, contact_id, data)
    payload_bytes = json.dumps(payload, sort_keys=True).encode()

    count = 0
    for hook in hooks:
        log_entry = WebhookDeliveryLog(
            webhook_id=hook.id,
            event_type=event_type,
            contact_id=contact_id,
            payload=payload,
            status=WebhookDeliveryStatus.PENDING,
        )
        db.add(log_entry)
        db.flush()  # get the ID

        hook.total_deliveries += 1
        hook.last_triggered_at = datetime.now(timezone.utc)

        if async_mode:
            try:
                from workers.tasks.webhooks import deliver_webhook
                deliver_webhook.apply_async(
                    kwargs={"delivery_log_id": log_entry.id},
                    queue="sync",
                )
            except Exception as exc:
                logger.warning("celery_unavailable_delivering_sync", error=str(exc))
                _deliver_sync(hook, log_entry, payload_bytes)
        else:
            _deliver_sync(hook, log_entry, payload_bytes)

        count += 1

    db.commit()
    return count


def _deliver_sync(hook: Webhook, log_entry: WebhookDeliveryLog, payload_bytes: bytes) -> None:
    """Deliver a single webhook synchronously. Updates log_entry in place."""
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "RevOps-LeadScoring/2.0",
        "X-Webhook-Event": log_entry.event_type,
        "X-Delivery-ID": log_entry.id,
    }
    if hook.secret:
        headers["X-Revops-Signature"] = f"sha256={_sign_payload(hook.secret, payload_bytes)}"

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(hook.url, content=payload_bytes, headers=headers)
        log_entry.http_status_code = resp.status_code
        log_entry.response_body = resp.text[:2000]
        if resp.is_success:
            log_entry.status = WebhookDeliveryStatus.SUCCESS
            log_entry.delivered_at = datetime.now(timezone.utc)
            hook.successful_deliveries += 1
            logger.info("webhook_delivered", webhook_id=hook.id, status=resp.status_code)
        else:
            log_entry.status = WebhookDeliveryStatus.FAILED
            hook.failed_deliveries += 1
            logger.warning("webhook_non_2xx", webhook_id=hook.id, status=resp.status_code)
    except Exception as exc:
        log_entry.status = WebhookDeliveryStatus.FAILED
        log_entry.error_message = str(exc)[:500]
        hook.failed_deliveries += 1
        logger.error("webhook_delivery_error", webhook_id=hook.id, error=str(exc))


def retry_failed_delivery(db: Session, delivery_log_id: str) -> bool:
    """
    Retry a failed delivery with exponential backoff.
    Returns True if a retry was scheduled.
    """
    log_entry = db.get(WebhookDeliveryLog, delivery_log_id)
    if not log_entry or log_entry.status == WebhookDeliveryStatus.SUCCESS:
        return False

    if log_entry.attempt_number >= MAX_ATTEMPTS:
        logger.warning("webhook_max_retries_exceeded", delivery_id=delivery_log_id)
        return False

    hook = db.get(Webhook, log_entry.webhook_id)
    if not hook or hook.status != "active":
        return False

    payload_bytes = json.dumps(log_entry.payload, sort_keys=True).encode()
    log_entry.attempt_number += 1
    log_entry.status = WebhookDeliveryStatus.RETRYING

    _deliver_sync(hook, log_entry, payload_bytes)
    db.commit()
    return True
