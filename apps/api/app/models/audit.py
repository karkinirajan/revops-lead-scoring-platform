import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditLog(Base):
    """Append-only audit trail for score overrides and privileged actions."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_id: Mapped[str | None] = mapped_column(String(64), index=True)  # user_id or "system"
    actor_email: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    before_value: Mapped[dict | None] = mapped_column(JSONB)
    after_value: Mapped[dict | None] = mapped_column(JSONB)
    trace_id: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )


class CrmSyncLog(Base):
    """Records every CRM sync attempt for audit and retry analysis."""

    __tablename__ = "crm_sync_logs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    contact_id: Mapped[str | None] = mapped_column(String(64), index=True)
    company_id: Mapped[str | None] = mapped_column(String(64), index=True)
    crm_system: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    crm_record_id: Mapped[str | None] = mapped_column(String(50))
    operation: Mapped[str] = mapped_column(String(20), nullable=False)  # upsert | create | update | delete
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # success | failed | retrying
    http_status_code: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    payload_hash: Mapped[str | None] = mapped_column(String(64))  # SHA-256 of request body
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    job_id: Mapped[str | None] = mapped_column(String(64), index=True)
