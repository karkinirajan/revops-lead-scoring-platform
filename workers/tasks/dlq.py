"""
Dead-letter queue reprocessor.

Periodically scans for quarantined/failed raw events and retries them
with controlled concurrency and rate limiting.
"""

from __future__ import annotations

import structlog

from workers.celery_app import app

logger = structlog.get_logger(__name__)

_MAX_DLQ_RETRY = 3
_REPROCESS_BATCH = 50  # records per run


@app.task(
    name="workers.tasks.dlq.reprocess_dlq",
    bind=True,
    max_retries=1,
    soft_time_limit=300,
)
def reprocess_dlq(self):
    """
    Every 30 min: find failed/quarantined events that haven't exceeded
    MAX_DLQ_RETRY and re-dispatch them through the ingest pipeline.
    """
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models.ingestion import RawEvent
    from workers.tasks.ingest import process_raw_event

    db = SessionLocal()
    try:
        # Find retryable failed events
        retryable = db.scalars(
            select(RawEvent)
            .where(
                RawEvent.processed == False,  # noqa: E712
                RawEvent.quarantined == False,  # noqa: E712
                RawEvent.retry_count < _MAX_DLQ_RETRY,
            )
            .order_by(RawEvent.ingested_at.asc())
            .limit(_REPROCESS_BATCH)
        ).all()

        if not retryable:
            logger.info("dlq_empty")
            return {"status": "empty"}

        logger.info("dlq_reprocessing", count=len(retryable))

        for event in retryable:
            event.retry_count += 1
            db.commit()
            process_raw_event.apply_async(
                kwargs={"raw_event_id": event.id},
                queue="ingest",
                countdown=event.retry_count * 30,  # linear backoff
            )

        return {"status": "dispatched", "count": len(retryable)}
    except Exception as exc:
        db.rollback()
        logger.error("dlq_reprocess_failed", error=str(exc))
        raise
    finally:
        db.close()


@app.task(
    name="workers.tasks.dlq.get_dlq_stats",
    bind=True,
    max_retries=1,
)
def get_dlq_stats(self) -> dict:
    """Return counts of quarantined and failed records for monitoring."""
    from sqlalchemy import func, select

    from app.database import SessionLocal
    from app.models.ingestion import RawEvent

    db = SessionLocal()
    try:
        quarantined = db.scalar(select(func.count(RawEvent.id)).where(RawEvent.quarantined == True))  # noqa: E712
        failed_retryable = db.scalar(
            select(func.count(RawEvent.id)).where(
                RawEvent.processed == False,  # noqa: E712
                RawEvent.quarantined == False,  # noqa: E712
                RawEvent.retry_count < _MAX_DLQ_RETRY,
            )
        )
        exhausted = db.scalar(
            select(func.count(RawEvent.id)).where(
                RawEvent.processed == False,  # noqa: E712
                RawEvent.retry_count >= _MAX_DLQ_RETRY,
            )
        )
        return {
            "quarantined": quarantined,
            "failed_retryable": failed_retryable,
            "retry_exhausted": exhausted,
        }
    finally:
        db.close()
