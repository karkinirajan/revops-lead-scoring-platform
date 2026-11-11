"""Conversion events — closed-loop feedback for model accuracy tracking."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.contact import Contact


class Conversion(Base):
    """
    Records when a contact became a paying customer (deal-won event).

    Populated via:
      - HubSpot deal-won webhook  (POST /api/v1/analytics/conversions/webhook)
      - Manual entry              (POST /api/v1/analytics/conversions)
      - CSV import                (CLI: import-conversions)

    Used to compute model accuracy (precision/recall per tier) and to
    generate the labeled dataset for v2 ML model training.
    """

    __tablename__ = "conversions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))

    contact_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Outcome data
    converted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    deal_value: Mapped[float | None] = mapped_column(Float)  # USD
    days_to_close: Mapped[int | None] = mapped_column(Integer)  # from first contact to close
    plan_tier: Mapped[str | None] = mapped_column(String(50))  # starter | pro | enterprise

    # Score snapshot at conversion — critical for calibration
    score_at_conversion: Mapped[int | None] = mapped_column(Integer)
    tier_at_conversion: Mapped[str | None] = mapped_column(String(10), index=True)
    model_version_at_conversion: Mapped[str | None] = mapped_column(String(20))

    # Source of this conversion event
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")  # hubspot_webhook | manual | csv
    crm_deal_id: Mapped[str | None] = mapped_column(String(100), index=True)

    notes: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    contact: Mapped["Contact"] = relationship("Contact")
