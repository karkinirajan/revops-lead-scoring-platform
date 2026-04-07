import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PriorityTier(StrEnum):
    HOT = "HOT"
    WARM = "WARM"
    COOL = "COOL"
    COLD = "COLD"


class ScoringRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class LeadScore(Base):
    """Versioned score output for a contact at a point in time."""

    __tablename__ = "lead_scores"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    contact_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("companies.id"), index=True)
    scoring_run_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("scoring_runs.id"), index=True)

    # Score output
    lead_score: Mapped[int] = mapped_column(Integer, nullable=False)
    priority_tier: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Explainability
    score_reason: Mapped[str | None] = mapped_column(Text)
    feature_contributions: Mapped[dict | None] = mapped_column(JSONB)
    feature_snapshot: Mapped[dict | None] = mapped_column(JSONB)

    # Recommended action
    recommended_action: Mapped[str | None] = mapped_column(String(100))

    # Shadow mode — set True for side-by-side model comparison runs
    is_shadow: Mapped[bool] = mapped_column(Integer, default=False, nullable=False)

    # Timestamps
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    feature_freshness_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # CRM sync state
    synced_to_hubspot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    contact: Mapped["Contact"] = relationship("Contact", back_populates="scores")  # noqa: F821
    scoring_run: Mapped["ScoringRun | None"] = relationship("ScoringRun", back_populates="scores")


class ScoringRun(Base):
    """Tracks a full or partial batch scoring execution."""

    __tablename__ = "scoring_runs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    model_version: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ScoringRunStatus.PENDING)

    # Run parameters
    filter_segment: Mapped[str | None] = mapped_column(String(50))  # all | smb | mid_market | enterprise
    is_shadow: Mapped[bool] = mapped_column(Integer, default=False, nullable=False)
    triggered_by: Mapped[str | None] = mapped_column(String(100))  # user_id or "scheduler"

    # Metrics
    total_contacts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scored_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Timing
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)

    error_detail: Mapped[str | None] = mapped_column(Text)

    scores: Mapped[list["LeadScore"]] = relationship("LeadScore", back_populates="scoring_run", lazy="select")
