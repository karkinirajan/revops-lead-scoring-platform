import uuid
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import AnalystRequired
from app.database import get_db
from app.models.ingestion import RawEvent

router = APIRouter()
logger = structlog.get_logger(__name__)
MAX_BATCH = 500


class IngestPayload(BaseModel):
    source_system: str = Field(min_length=1, max_length=50)
    source_record_id: str = Field(min_length=1, max_length=255)
    operation: str  # insert | update | delete (checked per event, so one bad event does not reject a batch)
    event_time: datetime | None = None
    schema_version: int = Field(default=1, ge=1, le=1000)
    raw_payload: dict
    trace_id: str | None = Field(default=None, max_length=64)


class IngestResponse(BaseModel):
    raw_event_id: str
    accepted: bool
    message: str


def _to_event(body: IngestPayload) -> RawEvent:
    return RawEvent(
        id=str(uuid.uuid4()),
        source_system=body.source_system,
        source_record_id=body.source_record_id,
        operation=body.operation,
        schema_version=body.schema_version,
        event_time=body.event_time,
        ingested_at=datetime.now(UTC),
        raw_payload=body.raw_payload,
        trace_id=body.trace_id,
    )


def _enqueue(event_ids: list[str]) -> bool:
    """Hand the stored events to the ingest queue. The events are already saved, so a queue that is down is logged, not fatal: they stay unprocessed."""
    try:
        from workers.tasks.ingest import process_raw_event

        for event_id in event_ids:
            process_raw_event.delay(raw_event_id=event_id)
    except Exception as exc:
        logger.error("ingest_enqueue_failed", count=len(event_ids), error=str(exc), error_type=type(exc).__name__)
        return False
    return True


@router.post("", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED, dependencies=[AnalystRequired])
def ingest_event(body: IngestPayload, db: Annotated[Session, Depends(get_db)]):
    """Accept a single raw event from any connector. Validates contract and enqueues for processing."""
    if body.operation not in ("insert", "update", "delete"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="operation must be insert|update|delete"
        )

    event = _to_event(body)
    db.add(event)
    db.commit()

    queued = _enqueue([event.id])
    message = "Event accepted for processing" if queued else "Event stored; the processing queue is unavailable"
    return IngestResponse(raw_event_id=event.id, accepted=True, message=message)


@router.post(
    "/batch", response_model=list[IngestResponse], status_code=status.HTTP_202_ACCEPTED, dependencies=[AnalystRequired]
)
def ingest_batch(events: list[IngestPayload], db: Annotated[Session, Depends(get_db)]):
    """Bulk ingest up to 500 events per request."""
    if len(events) > MAX_BATCH:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Batch size limited to {MAX_BATCH}")

    results = []
    raw_events = []
    for body in events:
        if body.operation not in ("insert", "update", "delete"):
            results.append(
                IngestResponse(raw_event_id="", accepted=False, message=f"Invalid operation: {body.operation[:20]}")
            )
            continue
        ev = _to_event(body)
        raw_events.append(ev)
        results.append(IngestResponse(raw_event_id=ev.id, accepted=True, message="Accepted"))

    db.add_all(raw_events)
    db.commit()
    _enqueue([ev.id for ev in raw_events])
    return results
