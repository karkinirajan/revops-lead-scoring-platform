"""Webhook targets and delivery audit log."""
import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WebhookEvent(StrEnum):
    TIER_CROSSED    = "tier_crossed"       # lead moves to a new tier
    SCORE_UPDATED   = "score_updated"      # any re-score
    DEMO_REQUESTED  = "demo_requested"     # intent signal fires
    HOT_LEAD        = "hot_lead"           # score enters HOT tier
    CONVERSION      = "conversion"         # deal-won recorded


class WebhookStatus(StrEnum):
    ACTIVE   = "active"
    PAUSED   = "paused"
    DISABLED = "disabled"


class WebhookDeliveryStatus(StrEnum):
    PENDING  = "pending"
    SUCCESS  = "success"
    FAILED   = "failed"
    RETRYING = "retrying"


class Webhook(Base):
    """A registered webhook endpoint."""

    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Owner
    created_by: Mapped[str | None] = mapped_column(String(64), index=True)

    # Target
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    secret: Mapped[str | None] = mapped_column(String(255))    # HMAC signing secret

    # What events trigger this webhook (stored as comma-separated string for portability)
    events: Mapped[str] = mapped_column(String(500), nullable=False, default="tier_crossed")

    # Filters — only fire for these tiers (empty = all tiers)
    tier_filter: Mapped[str | None] = mapped_column(String(100))  # "HOT,WARM"

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=WebhookStatus.ACTIVE, index=True)

    # Stats
    total_deliveries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successful_deliveries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_deliveries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    deliveries: Mapped[list["WebhookDeliveryLog"]] = relationship(
        "WebhookDeliveryLog", back_populates="webhook", lazy="select"
    )

    @property
    def event_list(self) -> list[str]:
        return [e.strip() for e in self.events.split(",") if e.strip()]

    @property
    def tier_filter_list(self) -> list[str]:
        if not self.tier_filter:
            return []
        return [t.strip().upper() for t in self.tier_filter.split(",") if t.strip()]


class WebhookDeliveryLog(Base):
    """Immutable record of every webhook delivery attempt."""

    __tablename__ = "webhook_delivery_logs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    webhook_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("webhooks.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Event context
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    contact_id: Mapped[str | None] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Delivery outcome
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=WebhookDeliveryStatus.PENDING, index=True)
    http_status_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)

    # Retry tracking
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )

    webhook: Mapped["Webhook"] = relationship("Webhook", back_populates="deliveries")
