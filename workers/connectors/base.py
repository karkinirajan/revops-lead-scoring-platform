"""
Base connector contract.

All source connectors must implement this interface so the pipeline
can treat HubSpot, Salesforce, CSV, and any future source uniformly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ConnectorRecord:
    """Normalized record envelope — maps to RawEvent schema."""

    source_system: str
    source_record_id: str
    operation: str  # insert | update | delete
    event_time: datetime | None
    schema_version: int
    raw_payload: dict[str, Any]
    trace_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "source_system": self.source_system,
            "source_record_id": self.source_record_id,
            "operation": self.operation,
            "event_time": self.event_time.isoformat() if self.event_time else None,
            "schema_version": self.schema_version,
            "raw_payload": self.raw_payload,
            "trace_id": self.trace_id,
        }


@dataclass
class CheckpointState:
    connector_id: str
    last_successful_watermark: str | None = None
    meta: dict = field(default_factory=dict)


class BaseConnector(ABC):
    """
    Abstract connector. Implementations must be stateless and idempotent.

    Lifecycle per run:
      1. load_checkpoint()   — restore watermark from DB
      2. fetch()             — pull records from source since watermark
      3. normalize()         — map each record to ConnectorRecord
      4. publish()           — push ConnectorRecords to the ingest queue
      5. save_checkpoint()   — persist new watermark on success
    """

    schema_version: int = 1

    def __init__(self, connector_id: str):
        self.connector_id = connector_id

    # ---- Required ----

    @abstractmethod
    def fetch(self, watermark: str | None) -> list[dict]:
        """
        Pull raw records from the source since the given watermark.
        If watermark is None, perform a full backfill.
        Returns a list of raw source records.
        """

    @abstractmethod
    def normalize(self, raw_record: dict) -> ConnectorRecord | None:
        """
        Map a single raw source record to a ConnectorRecord.
        Return None to skip/quarantine the record.
        """

    # ---- Checkpoint helpers (uses DB via SQLAlchemy) ----

    def load_checkpoint(self) -> CheckpointState:
        from sqlalchemy import select
        from app.database import SessionLocal
        from app.models.ingestion import WorkerCheckpoint

        db = SessionLocal()
        try:
            row = db.scalar(select(WorkerCheckpoint).where(WorkerCheckpoint.connector_id == self.connector_id))
            if row:
                return CheckpointState(
                    connector_id=self.connector_id,
                    last_successful_watermark=row.last_successful_watermark,
                    meta=row.meta or {},
                )
            return CheckpointState(connector_id=self.connector_id)
        finally:
            db.close()

    def save_checkpoint(self, watermark: str, records_processed: int = 0, meta: dict | None = None) -> None:
        import uuid
        from datetime import timezone
        from sqlalchemy import select
        from app.database import SessionLocal
        from app.models.ingestion import WorkerCheckpoint

        db = SessionLocal()
        try:
            row = db.scalar(select(WorkerCheckpoint).where(WorkerCheckpoint.connector_id == self.connector_id))
            if row is None:
                row = WorkerCheckpoint(id=str(uuid.uuid4()), connector_id=self.connector_id)
                db.add(row)
            row.last_successful_watermark = watermark
            row.last_run_at = datetime.now(timezone.utc if hasattr(datetime, "UTC") else None)
            row.last_run_status = "success"
            row.records_processed = records_processed
            row.meta = meta or {}
            db.commit()
        finally:
            db.close()

    # ---- Publish helpers ----

    def publish(self, records: list[ConnectorRecord]) -> int:
        """Publish normalized records to the ingest queue. Returns count published."""
        from workers.tasks.ingest import process_raw_event
        import uuid as _uuid
        from app.database import SessionLocal
        from app.models.ingestion import RawEvent
        from datetime import datetime, timezone

        db = SessionLocal()
        published = 0
        try:
            batch = []
            for rec in records:
                ev = RawEvent(
                    id=str(_uuid.uuid4()),
                    source_system=rec.source_system,
                    source_record_id=rec.source_record_id,
                    operation=rec.operation,
                    schema_version=rec.schema_version,
                    event_time=rec.event_time,
                    ingested_at=datetime.now(timezone.utc),
                    raw_payload=rec.raw_payload,
                    trace_id=rec.trace_id,
                )
                batch.append(ev)

                if len(batch) >= 500:
                    db.add_all(batch)
                    db.commit()
                    for ev in batch:
                        process_raw_event.delay(raw_event_id=ev.id)
                    published += len(batch)
                    batch = []

            if batch:
                db.add_all(batch)
                db.commit()
                for ev in batch:
                    process_raw_event.delay(raw_event_id=ev.id)
                published += len(batch)
        finally:
            db.close()

        return published

    def run(self) -> dict:
        """Full connector run: fetch → normalize → publish → checkpoint."""
        import structlog
        log = structlog.get_logger(self.__class__.__name__)

        checkpoint = self.load_checkpoint()
        watermark = checkpoint.last_successful_watermark
        log.info("connector_run_started", connector_id=self.connector_id, watermark=watermark)

        raw_records = self.fetch(watermark)
        log.info("connector_fetched", count=len(raw_records))

        normalized = []
        skipped = 0
        for raw in raw_records:
            rec = self.normalize(raw)
            if rec:
                normalized.append(rec)
            else:
                skipped += 1

        published = self.publish(normalized)
        new_watermark = self._extract_watermark(raw_records)

        if new_watermark:
            self.save_checkpoint(new_watermark, records_processed=published)

        log.info("connector_run_complete", published=published, skipped=skipped)
        return {"published": published, "skipped": skipped, "watermark": new_watermark}

    def _extract_watermark(self, records: list[dict]) -> str | None:
        """Override to extract a new watermark from the last batch of raw records."""
        return None
