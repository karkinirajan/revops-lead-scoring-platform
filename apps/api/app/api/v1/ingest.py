import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import AnalystRequired
from app.database import get_db
from app.models.ingestion import RawEvent

router = APIRouter()


class IngestPayload(BaseModel):
    source_system: str
    source_record_id: str
    operation: str  # insert | update | delete
    event_time: datetime | None = None
    schema_version: int = 1
    raw_payload: dict
    trace_id: str | None = None


class IngestResponse(BaseModel):
    raw_event_id: str
    accepted: bool
    message: str


@router.post("", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED, dependencies=[AnalystRequired])
def ingest_event(body: IngestPayload, db: Annotated[Session, Depends(get_db)]):
    """Accept a single raw event from any connector. Validates contract and enqueues for processing."""
    if body.operation not in ("insert", "update", "delete"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="operation must be insert|update|delete")

    event = RawEvent(
        id=str(uuid.uuid4()),
        source_system=body.source_system,
        source_record_id=body.source_record_id,
        operation=body.operation,
        schema_version=body.schema_version,
        event_time=body.event_time,
        ingested_at=datetime.now(timezone.utc),
        raw_payload=body.raw_payload,
        trace_id=body.trace_id,
    )
    db.add(event)
    db.commit()

    # Dispatch to ingest queue
    try:
        from workers.tasks.ingest import process_raw_event
        process_raw_event.delay(raw_event_id=event.id)
    except Exception:
        pass

    return IngestResponse(raw_event_id=event.id, accepted=True, message="Event accepted for processing")


@router.post("/batch", response_model=list[IngestResponse], status_code=status.HTTP_202_ACCEPTED, dependencies=[AnalystRequired])
def ingest_batch(events: list[IngestPayload], db: Annotated[Session, Depends(get_db)]):
    """Bulk ingest up to 500 events per request."""
    if len(events) > 500:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Batch size limited to 500")

    results = []
    raw_events = []
    for body in events:
        if body.operation not in ("insert", "update", "delete"):
            results.append(IngestResponse(raw_event_id="", accepted=False, message=f"Invalid operation: {body.operation}"))
            continue
        ev = RawEvent(
            id=str(uuid.uuid4()),
            source_system=body.source_system,
            source_record_id=body.source_record_id,
            operation=body.operation,
            schema_version=body.schema_version,
            event_time=body.event_time,
            ingested_at=datetime.now(timezone.utc),
            raw_payload=body.raw_payload,
            trace_id=body.trace_id,
        )
        raw_events.append(ev)
        results.append(IngestResponse(raw_event_id=ev.id, accepted=True, message="Accepted"))

    db.add_all(raw_events)
    db.commit()

    # Dispatch tasks in bulk
    try:
        from workers.tasks.ingest import process_raw_event
        for ev in raw_events:
            process_raw_event.delay(raw_event_id=ev.id)
    except Exception:
        pass

    return results
