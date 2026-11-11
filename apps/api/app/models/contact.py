import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.scoring import LeadScore


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("source_system", "source_record_id", name="uq_contact_source"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Source lineage
    source_system: Mapped[str] = mapped_column(String(50), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Core identity
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    job_title: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))

    # Company FK
    company_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("companies.id"), index=True)

    # CRM metadata
    lifecycle_stage: Mapped[str | None] = mapped_column(String(50))
    lead_status: Mapped[str | None] = mapped_column(String(50))
    hubspot_contact_id: Mapped[str | None] = mapped_column(String(50), index=True)
    crm_owner_id: Mapped[str | None] = mapped_column(String(50))

    # Activity timestamps
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Metadata
    extra: Mapped[dict | None] = mapped_column(JSONB)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    company: Mapped["Company | None"] = relationship("Company", back_populates="contacts")
    features: Mapped["ContactFeature | None"] = relationship("ContactFeature", back_populates="contact", uselist=False)
    scores: Mapped[list["LeadScore"]] = relationship("LeadScore", back_populates="contact", lazy="select")

    @property
    def full_name(self) -> str:
        parts = [p for p in [self.first_name, self.last_name] if p]
        return " ".join(parts) if parts else self.email

    def __repr__(self) -> str:
        return f"<Contact id={self.id} email={self.email!r}>"


class ContactFeature(Base):
    """Pre-aggregated scoring features for a contact. Refreshed incrementally."""

    __tablename__ = "contact_features"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    contact_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("contacts.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )

    # API usage (core signal)
    api_calls_1d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    api_calls_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    api_calls_30d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Web engagement
    page_views_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page_views_30d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pricing_page_visited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    docs_page_visits_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Email engagement
    email_opens_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    email_clicks_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    email_opens_30d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Intent signals
    demo_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    free_trial_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    integration_connected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    integrations_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Recency
    days_since_last_activity: Mapped[int] = mapped_column(Integer, default=999, nullable=False)
    days_since_last_email_open: Mapped[int] = mapped_column(Integer, default=999, nullable=False)

    # Computed aggregates
    sessions_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_session_duration_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Feature freshness
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    contact: Mapped["Contact"] = relationship("Contact", back_populates="features")
