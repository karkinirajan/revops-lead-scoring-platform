"""
Scoring worker tasks — batch and incremental contact scoring.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog

from workers.celery_app import app

logger = structlog.get_logger(__name__)


def _get_db():
    from app.database import SessionLocal

    return SessionLocal()


def _record_progress(db, run_id: str | None, *, scored: int = 0, errors: int = 0) -> None:
    """Count one contact as scored (or failed) in its run, and close the run when every contact has been accounted for.

    The counters are incremented in SQL, so tasks running at the same time do not overwrite each other. The caller commits.
    """
    if not run_id:
        return
    from sqlalchemy import update

    from app.models.scoring import ScoringRun, ScoringRunStatus

    row = db.execute(
        update(ScoringRun)
        .where(ScoringRun.id == run_id)
        .values(scored_count=ScoringRun.scored_count + scored, error_count=ScoringRun.error_count + errors)
        .returning(ScoringRun.scored_count, ScoringRun.error_count, ScoringRun.total_contacts, ScoringRun.started_at)
    ).one_or_none()
    if row is None:
        return
    done, failed, total, started = row
    if total and done + failed >= total:
        now = datetime.now(UTC)
        status = (
            ScoringRunStatus.COMPLETED
            if not failed
            else ScoringRunStatus.FAILED
            if not done
            else ScoringRunStatus.PARTIAL
        )
        db.execute(
            update(ScoringRun)
            .where(ScoringRun.id == run_id, ScoringRun.status == ScoringRunStatus.RUNNING)
            .values(status=status, completed_at=now, duration_seconds=(now - started).total_seconds())
        )


class _ScoringTask(app.Task):
    """A scoring task that counts a contact as failed in its run once its retries are used up."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        run_id = kwargs.get("run_id") or (args[1] if len(args) > 1 else None)
        db = _get_db()
        try:
            _record_progress(db, run_id, errors=1)
            db.commit()
        except Exception as error:  # the original failure is what matters; do not hide it behind this one
            db.rollback()
            logger.error("scoring_failure_not_recorded", run_id=run_id, error=str(error))
        finally:
            db.close()


@app.task(
    name="workers.tasks.scoring.score_single_contact",
    base=_ScoringTask,
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def score_single_contact(
    self, contact_id: str, run_id: str | None = None, is_shadow: bool = False, use_ml_model: bool = False
):
    """Score a single contact and persist the result."""
    from app.models.contact import Contact
    from app.services.lead_scoring import feature_vector, latest_live_score, new_score
    from app.services.scoring_engine import score_contact
    from app.services.webhook_service import notify_score_change

    db = _get_db()
    try:
        contact = db.get(Contact, contact_id)
        if not contact:
            return {"status": "not_found", "contact_id": contact_id}

        previous = latest_live_score(db, contact_id)  # what a live score is compared with

        fv = feature_vector(contact)

        # Use ML model if requested and champion is available
        if use_ml_model:
            from app.services.ml_scoring_engine import get_champion_model_path, score_contact_ml

            champion = get_champion_model_path()
            if champion:
                artifact_path, model_version = champion
                result = score_contact_ml(fv, artifact_path, model_version)
            else:
                result = score_contact(fv)
        else:
            result = score_contact(fv)

        score = new_score(contact, fv, result, run_id=run_id, is_shadow=is_shadow)
        db.add(score)
        _record_progress(db, run_id, scored=1)
        db.commit()

        logger.info(
            "contact_scored",
            contact_id=contact_id,
            score=result.lead_score,
            tier=result.priority_tier,
            run_id=run_id,
        )
        if not is_shadow:
            # after the commit, and never allowed to fail the task: the score is saved, and a retry would score the contact twice
            notify_score_change(db, contact, previous, score, fv.demo_requested)
        return {"status": "ok", "contact_id": contact_id, "score": result.lead_score, "tier": result.priority_tier}
    except Exception as exc:
        db.rollback()
        logger.error("scoring_failed", contact_id=contact_id, error=str(exc))
        raise self.retry(exc=exc) from exc
    finally:
        db.close()


@app.task(
    name="workers.tasks.scoring.run_scoring_batch",
    bind=True,
    max_retries=1,
    soft_time_limit=600,
)
def run_scoring_batch(
    self,
    run_id: str | None = None,
    filter_segment: str | None = None,
    is_shadow: bool = False,
    use_ml_model: bool = False,
):
    """
    Full batch scoring pass. Creates a ScoringRun record, then
    fans out score_single_contact tasks for each contact.
    """
    from sqlalchemy import select

    from app.config import get_settings
    from app.database import SessionLocal
    from app.models.company import Company
    from app.models.contact import Contact
    from app.models.scoring import ScoringRun, ScoringRunStatus

    settings = get_settings()
    db = SessionLocal()
    try:
        # Create or fetch run record
        run = db.get(ScoringRun, run_id) if run_id else None

        if run is None:
            run = ScoringRun(
                id=str(uuid.uuid4()),
                model_version=settings.scoring_model_version,
                status=ScoringRunStatus.RUNNING,
                filter_segment=filter_segment,
                is_shadow=is_shadow,
                triggered_by="scheduler",
                started_at=datetime.now(UTC),
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
        if not contact_ids:  # nothing to score: the run is complete now (no task would ever close it)
            run.status = ScoringRunStatus.COMPLETED
            run.completed_at = datetime.now(UTC)
            run.duration_seconds = (run.completed_at - run.started_at).total_seconds()
        db.commit()
        db.close()

        logger.info("scoring_batch_started", run_id=run_id, total=len(contact_ids), is_shadow=is_shadow)

        # Fan out per-contact tasks
        for cid in contact_ids:
            score_single_contact.delay(contact_id=cid, run_id=run_id, is_shadow=is_shadow, use_ml_model=use_ml_model)

        return {"status": "dispatched", "run_id": run_id, "total": len(contact_ids)}
    except Exception as exc:
        db.rollback()
        db.close()
        logger.error("scoring_batch_failed", error=str(exc), exc_info=True)
        raise


@app.task(
    name="workers.tasks.scoring.retrain_ml_model",
    bind=True,
    max_retries=1,
    soft_time_limit=1800,
)
def retrain_ml_model(self, min_rows: int = 200, promote: bool = False):
    """
    Periodic task: retrain XGBoost model v2 from latest conversion data.
    By default registers as shadow (promote=False).
    Promote to champion via the model registry API.
    """
    try:
        from workers.training.train_model import train

        version = train(min_rows=min_rows, shadow=not promote, promote=promote)
        logger.info("ml_model_retrained", version=version, promote=promote)
        return {"status": "ok", "version": version}
    except ValueError as exc:
        logger.warning("ml_retrain_skipped", reason=str(exc))
        return {"status": "skipped", "reason": str(exc)}
    except Exception as exc:
        logger.error("ml_retrain_failed", error=str(exc), exc_info=True)
        raise
