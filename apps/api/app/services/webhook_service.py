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
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.scoring import PriorityTier
from app.models.webhook import Webhook, WebhookDeliveryLog, WebhookDeliveryStatus, WebhookEvent
from app.security.urls import UnsafeUrlError, ensure_public_url

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.conversion import Conversion
    from app.models.scoring import LeadScore

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
        "timestamp": datetime.now(UTC).isoformat(),
        "data": data,
    }


def get_active_webhooks_for_event(db: Session, event_type: str, tier: str | None = None) -> list[Webhook]:
    """Return all active webhooks subscribed to this event (and matching tier filter)."""
    hooks = db.scalars(select(Webhook).where(Webhook.status == "active")).all()

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

    pending: list[tuple[Webhook, WebhookDeliveryLog]] = []
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
        hook.last_triggered_at = datetime.now(UTC)
        pending.append((hook, log_entry))

    # A worker asked to deliver a row looks it up in its own session, so the rows must be committed before any worker is asked: otherwise a fast worker finds
    # nothing and the event is dropped.
    db.commit()

    for hook, log_entry in pending:
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

    db.commit()
    return len(pending)


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
        ensure_public_url(
            hook.url
        )  # checked again now: a name that was public when the webhook was saved may point inward today
        with httpx.Client(timeout=15.0, follow_redirects=False) as client:
            resp = client.post(hook.url, content=payload_bytes, headers=headers)
        log_entry.http_status_code = resp.status_code
        log_entry.response_body = resp.text[:2000]
        if resp.is_success:
            log_entry.status = WebhookDeliveryStatus.SUCCESS
            log_entry.delivered_at = datetime.now(UTC)
            hook.successful_deliveries += 1
            logger.info("webhook_delivered", webhook_id=hook.id, status=resp.status_code)
        else:
            log_entry.status = WebhookDeliveryStatus.FAILED
            hook.failed_deliveries += 1
            logger.warning("webhook_non_2xx", webhook_id=hook.id, status=resp.status_code)
    except UnsafeUrlError as exc:
        log_entry.status = WebhookDeliveryStatus.FAILED
        log_entry.error_message = f"refused to call this URL: {exc}"
        hook.failed_deliveries += 1
        logger.warning("webhook_target_refused", webhook_id=hook.id, reason=str(exc))
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


def send_test_delivery(
    db: Session, hook: Webhook, *, event_type: str, contact_id: str | None, data: dict
) -> WebhookDeliveryLog:
    """Deliver one test event to this webhook, synchronously, and return its delivery log entry."""
    payload = build_payload(event_type, contact_id, data)
    log_entry = WebhookDeliveryLog(
        webhook_id=hook.id,
        event_type=event_type,
        contact_id=contact_id,
        payload=payload,
        status=WebhookDeliveryStatus.PENDING,
    )
    db.add(log_entry)
    db.flush()
    hook.total_deliveries += 1
    hook.last_triggered_at = datetime.now(UTC)
    _deliver_sync(hook, log_entry, json.dumps(payload, sort_keys=True).encode())
    db.commit()
    return log_entry


# ---------------------------------------------------------------------------
# Events: what the platform tells subscribers about
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PreviousScore:
    """What a contact's previous live score looked like, to compare the new one with."""

    score: int
    tier: str
    demo_requested: bool


def score_events(previous: PreviousScore | None, *, score: int, tier: str, demo_requested: bool) -> list[str]:
    """The events a new live score gives rise to. They describe a change, so a contact's first score (nothing to compare with) gives rise to none: otherwise
    the first scoring pass would send an event for every HOT lead and every demo request already in the database."""
    if previous is None:
        return []
    events: list[str] = []
    if tier != previous.tier:
        events.append(WebhookEvent.TIER_CROSSED)
    if tier == PriorityTier.HOT and previous.tier != PriorityTier.HOT:
        events.append(WebhookEvent.HOT_LEAD)
    if score != previous.score:
        events.append(WebhookEvent.SCORE_UPDATED)
    if demo_requested and not previous.demo_requested:
        events.append(WebhookEvent.DEMO_REQUESTED)
    return events


def notify_score_change(
    db: Session, contact: Contact, previous: LeadScore | None, current: LeadScore, demo_requested: bool
) -> int:
    """Tell the subscribed webhooks what a new live score changed. Returns how many deliveries were started.

    Called after the score is saved. A failure here is logged and costs only the notification: it must neither lose the score nor make the scoring task retry.
    """
    try:
        before = (
            None
            if previous is None
            else PreviousScore(
                previous.lead_score,
                previous.priority_tier,
                bool((previous.feature_snapshot or {}).get("demo_requested")),
            )
        )
        events = score_events(
            before, score=current.lead_score, tier=current.priority_tier, demo_requested=demo_requested
        )
        if not events:
            return 0
        data = {
            "contact_email": contact.email,
            "lead_score": current.lead_score,
            "previous_score": before.score if before else None,
            "priority_tier": current.priority_tier,
            "previous_tier": before.tier if before else None,
            "score_reason": current.score_reason,
            "recommended_action": current.recommended_action,
            "model_version": current.model_version,
        }
        return sum(dispatch_event(db, event, contact.id, data, tier=current.priority_tier) for event in events)
    except Exception as exc:
        db.rollback()
        logger.error(
            "webhook_notification_failed", contact_id=contact.id, error=str(exc), error_type=type(exc).__name__
        )
        return 0


def notify_conversion(db: Session, contact: Contact, conversion: Conversion) -> int:
    """Tell the subscribed webhooks that a deal was won. Same contract as `notify_score_change`."""
    try:
        data = {
            "contact_email": contact.email,
            "deal_value": conversion.deal_value,
            "converted_at": conversion.converted_at.isoformat(),
            "source": conversion.source,
            "crm_deal_id": conversion.crm_deal_id,
            "plan_tier": conversion.plan_tier,
            "score_at_conversion": conversion.score_at_conversion,
            "tier_at_conversion": conversion.tier_at_conversion,
        }
        return dispatch_event(db, WebhookEvent.CONVERSION, contact.id, data, tier=conversion.tier_at_conversion)
    except Exception as exc:
        db.rollback()
        logger.error(
            "webhook_notification_failed", contact_id=contact.id, error=str(exc), error_type=type(exc).__name__
        )
        return 0
