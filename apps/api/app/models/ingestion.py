import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RawEvent(Base):
    """Immutable raw ingestion record. Never updated — append-only."""

    __tablename__ = "raw_events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Connector contract (all sources must populate these)
    source_system: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_record_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)  # insert | update | delete
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Timestamps from source and pipeline
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )

    # Immutable payload
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Processing state
    processed: Mapped[bool] = mapped_column(Integer, default=False, nullable=False, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Quarantine flag for schema-invalid records
    quarantined: Mapped[bool] = mapped_column(Integer, default=False, nullable=False, index=True)
    quarantine_reason: Mapped[str | None] = mapped_column(Text)

    # Correlation
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    job_id: Mapped[str | None] = mapped_column(String(64), index=True)

    def __repr__(self) -> str:
        return f"<RawEvent id={self.id} source={self.source_system} op={self.operation}>"


class WorkerCheckpoint(Base):
    """Per-connector watermark for incremental pulls."""

    __tablename__ = "worker_checkpoints"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    connector_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    last_successful_watermark: Mapped[str | None] = mapped_column(String(255))  # ISO datetime or cursor token
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_status: Mapped[str | None] = mapped_column(String(20))
    records_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
