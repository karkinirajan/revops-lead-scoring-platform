"""
Scoring worker tasks — batch and incremental contact scoring.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog

from workers.celery_app import app

logger = structlog.get_logger(__name__)


def _get_db():
    from app.database import SessionLocal
    return SessionLocal()


@app.task(
    name="workers.tasks.scoring.score_single_contact",
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def score_single_contact(self, contact_id: str, run_id: str | None = None, is_shadow: bool = False):
    """Score a single contact and persist the result."""
    from sqlalchemy import select
    from app.models.contact import Contact
    from app.models.scoring import LeadScore
    from app.services.scoring_engine import FeatureVector, score_contact

    db = _get_db()
    try:
        contact = db.get(Contact, contact_id)
        if not contact:
            return {"status": "not_found", "contact_id": contact_id}

        f = contact.features
        fv = FeatureVector(
            api_calls_7d=f.api_calls_7d if f else 0,
            api_calls_30d=f.api_calls_30d if f else 0,
            page_views_7d=f.page_views_7d if f else 0,
            pricing_page_visited=f.pricing_page_visited if f else False,
            email_opens_7d=f.email_opens_7d if f else 0,
            email_clicks_7d=f.email_clicks_7d if f else 0,
            docs_page_visits_7d=f.docs_page_visits_7d if f else 0,
            demo_requested=f.demo_requested if f else False,
            free_trial_active=f.free_trial_active if f else False,
            integration_connected=f.integration_connected if f else False,
            integrations_count=f.integrations_count if f else 0,
            sessions_7d=f.sessions_7d if f else 0,
            days_since_last_activity=f.days_since_last_activity if f else 999,
        )

        result = score_contact(fv)

        score = LeadScore(
            id=str(uuid.uuid4()),
            contact_id=contact_id,
            company_id=contact.company_id,
            scoring_run_id=run_id,
            lead_score=result.lead_score,
            priority_tier=result.priority_tier,
            model_version=result.model_version,
            score_reason=result.score_reason,
            feature_contributions=result.feature_contributions,
            feature_snapshot={
                "api_calls_7d": fv.api_calls_7d,
                "page_views_7d": fv.page_views_7d,
                "demo_requested": fv.demo_requested,
                "days_since_last_activity": fv.days_since_last_activity,
            },
            recommended_action=result.recommended_action,
            is_shadow=is_shadow,
            scored_at=datetime.now(timezone.utc),
            feature_freshness_at=f.computed_at if f else None,
        )
        db.add(score)
        db.commit()

        logger.info(
            "contact_scored",
            contact_id=contact_id,
            score=result.lead_score,
            tier=result.priority_tier,
            run_id=run_id,
        )
        return {"status": "ok", "contact_id": contact_id, "score": result.lead_score, "tier": result.priority_tier}
    except Exception as exc:
        db.rollback()
        logger.error("scoring_failed", contact_id=contact_id, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()


@app.task(
    name="workers.tasks.scoring.run_scoring_batch",
    bind=True,
    max_retries=1,
    soft_time_limit=600,
)
def run_scoring_batch(self, run_id: str | None = None, filter_segment: str | None = None, is_shadow: bool = False):
    """
    Full batch scoring pass. Creates a ScoringRun record, then
    fans out score_single_contact tasks for each contact.
    """
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models.contact import Contact
    from app.models.company import Company
    from app.models.scoring import ScoringRun, ScoringRunStatus
    from app.config import get_settings

    settings = get_settings()
    db = SessionLocal()
    try:
        # Create or fetch run record
        if run_id:
            run = db.get(ScoringRun, run_id)
        else:
            run = None

        if run is None:
            run = ScoringRun(
                id=str(uuid.uuid4()),
                model_version=settings.scoring_model_version,
                status=ScoringRunStatus.RUNNING,
                filter_segment=filter_segment,
                is_shadow=is_shadow,
                triggered_by="scheduler",
                started_at=datetime.now(timezone.utc),
            )
            db.add(run)
        else:
            run.status = ScoringRunStatus.RUNNING

        db.commit()
        run_id = run.id

        # Build contact query
        q = select(Contact.id)
        if filter_segment:
            q = q.join(Company, Contact.company_id == Company.id).where(Company.size_tier == filter_segment)

        contact_ids = db.scalars(q).all()
        run.total_contacts = len(contact_ids)
        db.commit()
        db.close()

        logger.info("scoring_batch_started", run_id=run_id, total=len(contact_ids), is_shadow=is_shadow)

        # Fan out per-contact tasks
        for cid in contact_ids:
            score_single_contact.delay(contact_id=cid, run_id=run_id, is_shadow=is_shadow)

        return {"status": "dispatched", "run_id": run_id, "total": len(contact_ids)}
    except Exception as exc:
        db.rollback()
        db.close()
        logger.error("scoring_batch_failed", error=str(exc), exc_info=True)
        raise
