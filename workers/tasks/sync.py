"""
CRM sync worker tasks — HubSpot batch upserts with retry and DLQ routing.
"""
from __future__ import annotations

import uuid

import structlog

from workers.celery_app import app

logger = structlog.get_logger(__name__)


def _get_db():
    from app.database import SessionLocal
    return SessionLocal()


@app.task(
    name="workers.tasks.sync.sync_contact_to_hubspot",
    bind=True,
    max_retries=5,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def sync_contact_to_hubspot(self, contact_id: str, score_id: str | None = None):
    """Sync a single contact's latest score to HubSpot."""
    from sqlalchemy import select, func
    from app.models.contact import Contact
    from app.models.scoring import LeadScore
    from app.services.crm_sync import sync_batch_to_hubspot

    db = _get_db()
    try:
        contact = db.get(Contact, contact_id)
        if not contact:
            return {"status": "not_found"}

        # Get latest score
        score = db.scalar(
            select(LeadScore)
            .where(LeadScore.contact_id == contact_id, LeadScore.is_shadow == False)  # noqa: E712
            .order_by(LeadScore.scored_at.desc())
            .limit(1)
        )
        if not score:
            return {"status": "no_score"}

        payload = {
            "id": contact_id,
            "email": contact.email,
            "lead_score": score.lead_score,
            "priority_tier": score.priority_tier,
            "score_reason": score.score_reason or "",
            "recommended_action": score.recommended_action or "",
            "model_version": score.model_version,
            "scored_at": score.scored_at.isoformat(),
        }

        success, failure = sync_batch_to_hubspot([payload], db_session=db, job_id=str(uuid.uuid4()))

        if success:
            from datetime import datetime, timezone
            score.synced_to_hubspot_at = datetime.now(timezone.utc)
            db.commit()

        return {"status": "ok" if success else "failed", "contact_id": contact_id}
    except Exception as exc:
        db.rollback()
        logger.error("hubspot_sync_task_failed", contact_id=contact_id, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()


@app.task(
    name="workers.tasks.sync.sync_top_leads_to_hubspot",
    bind=True,
    max_retries=2,
    soft_time_limit=1800,
)
def sync_top_leads_to_hubspot(self, top_n: int = 1000, min_score: int = 50):
    """
    Daily task: sync all WARM+ leads to HubSpot in batches.
    Uses batch upsert endpoint for efficiency.
    """
    from sqlalchemy import select, func
    from app.models.contact import Contact
    from app.models.company import Company
    from app.models.scoring import LeadScore
    from app.services.crm_sync import sync_batch_to_hubspot

    db = _get_db()
    try:
        latest = (
            select(LeadScore.contact_id, func.max(LeadScore.scored_at).label("max_scored_at"))
            .where(LeadScore.is_shadow == False, LeadScore.lead_score >= min_score)  # noqa: E712
            .group_by(LeadScore.contact_id)
            .subquery()
        )
        q = (
            select(LeadScore, Contact)
            .join(latest, (LeadScore.contact_id == latest.c.contact_id) & (LeadScore.scored_at == latest.c.max_scored_at))
            .join(Contact, LeadScore.contact_id == Contact.id)
            .order_by(LeadScore.lead_score.desc())
            .limit(top_n)
        )
        rows = db.execute(q).all()

        payloads = [
            {
                "id": contact.id,
                "email": contact.email,
                "lead_score": score.lead_score,
                "priority_tier": score.priority_tier,
                "score_reason": score.score_reason or "",
                "recommended_action": score.recommended_action or "",
                "model_version": score.model_version,
                "scored_at": score.scored_at.isoformat(),
            }
            for score, contact in rows
        ]
        db.close()

        if not payloads:
            logger.info("no_leads_to_sync")
            return {"status": "no_leads"}

        success, failure = sync_batch_to_hubspot(payloads, db_session=None)
        logger.info("daily_sync_complete", success=success, failure=failure, total=len(payloads))
        return {"status": "ok", "success": success, "failure": failure}
    except Exception as exc:
        db.rollback()
        db.close()
        logger.error("daily_sync_failed", error=str(exc))
        raise
