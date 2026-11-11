"""
Feature aggregation worker tasks.

Incrementally recomputes pre-aggregated feature rows for contacts.
In production these would pull from a time-series events table;
here we use a simplified approach that can be extended.
"""

from __future__ import annotations

from datetime import UTC

import structlog

from workers.celery_app import app

logger = structlog.get_logger(__name__)


def _get_db():
    from app.database import SessionLocal

    return SessionLocal()


def compute_features_for_contact(contact_id: str) -> None:
    """
    Recompute ContactFeature row for a single contact.
    This is the internal synchronous implementation called by both
    the Celery task and the CLI.
    """
    import uuid
    from datetime import datetime

    from sqlalchemy import select

    from app.models.contact import Contact, ContactFeature
    from app.models.ingestion import RawEvent

    db = _get_db()
    try:
        contact = db.get(Contact, contact_id)
        if not contact:
            logger.warning("contact_not_found_for_features", contact_id=contact_id)
            return

        # Pull raw events for this contact to aggregate signals
        events = db.scalars(
            select(RawEvent)
            .where(
                RawEvent.source_record_id == contact.source_record_id,
                RawEvent.source_system == contact.source_system,
                RawEvent.processed == True,  # noqa: E712
            )
            .order_by(RawEvent.event_time.desc())
            .limit(1000)
        ).all()

        # Aggregate signals from raw event payloads
        api_calls_7d = 0
        api_calls_30d = 0
        page_views_7d = 0
        email_opens_7d = 0
        email_clicks_7d = 0
        pricing_page_visited = False
        demo_requested = False

        now = datetime.now(UTC)
        for ev in events:
            p = ev.raw_payload
            event_type = p.get("event_type", "")
            event_age_days = 999
            if ev.event_time:
                event_age_days = (now - ev.event_time).days

            if event_type == "api_call":
                if event_age_days <= 7:
                    api_calls_7d += 1
                if event_age_days <= 30:
                    api_calls_30d += 1
            elif event_type == "page_view":
                if event_age_days <= 7:
                    page_views_7d += 1
                if p.get("page") in ("/pricing", "/plans", "/buy"):
                    pricing_page_visited = True
            elif event_type == "email_open" and event_age_days <= 7:
                email_opens_7d += 1
            elif event_type == "email_click" and event_age_days <= 7:
                email_clicks_7d += 1
            elif event_type == "demo_request":
                demo_requested = True

        # Days since last activity
        days_since = 999
        if contact.last_activity_at:
            days_since = (now - contact.last_activity_at).days
        elif events and events[0].event_time:
            days_since = (now - events[0].event_time).days

        # Upsert feature row
        feat = db.scalar(select(ContactFeature).where(ContactFeature.contact_id == contact_id))
        if feat is None:
            feat = ContactFeature(id=str(uuid.uuid4()), contact_id=contact_id)
            db.add(feat)

        feat.api_calls_7d = api_calls_7d
        feat.api_calls_30d = api_calls_30d
        feat.page_views_7d = page_views_7d
        feat.email_opens_7d = email_opens_7d
        feat.email_clicks_7d = email_clicks_7d
        feat.pricing_page_visited = pricing_page_visited
        feat.demo_requested = demo_requested
        feat.days_since_last_activity = days_since
        feat.computed_at = now

        db.commit()
        logger.info("features_computed", contact_id=contact_id)
    except Exception as exc:
        db.rollback()
        logger.error("features_computation_failed", contact_id=contact_id, error=str(exc))
        raise
    finally:
        db.close()


@app.task(
    name="workers.tasks.features.compute_features_for_contact_task",
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def compute_features_for_contact_task(self, contact_id: str):
    compute_features_for_contact(contact_id=contact_id)


@app.task(
    name="workers.tasks.features.recompute_all_features",
    bind=True,
    max_retries=1,
)
def recompute_all_features(self, batch_size: int = 500):
    """
    Hourly job: recompute features for all contacts in batches.
    Shards by contact_id hash into smaller parallel tasks.
    """
    from sqlalchemy import func, select

    from app.database import SessionLocal
    from app.models.contact import Contact

    db = SessionLocal()
    try:
        total = db.scalar(select(func.count(Contact.id)))
        logger.info("feature_recompute_started", total_contacts=total)

        contact_ids = db.scalars(select(Contact.id)).all()
        db.close()

        # Dispatch individual tasks
        for i in range(0, len(contact_ids), batch_size):
            chunk = contact_ids[i : i + batch_size]
            for cid in chunk:
                compute_features_for_contact_task.delay(contact_id=cid)

        logger.info("feature_recompute_dispatched", total_dispatched=len(contact_ids))
        return {"dispatched": len(contact_ids)}
    except Exception:
        db.close()
        raise
