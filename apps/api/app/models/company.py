import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.contact import Contact


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Source lineage
    source_system: Mapped[str] = mapped_column(String(50), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Core fields
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    industry: Mapped[str | None] = mapped_column(String(100))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    annual_revenue: Mapped[int | None] = mapped_column(Integer)
    country: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))

    # Segmentation
    size_tier: Mapped[str | None] = mapped_column(String(20))  # smb | mid_market | enterprise
    lifecycle_stage: Mapped[str | None] = mapped_column(String(50))

    # CRM sync
    hubspot_company_id: Mapped[str | None] = mapped_column(String(50), index=True)
    crm_owner_id: Mapped[str | None] = mapped_column(String(50))

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
    contacts: Mapped[list["Contact"]] = relationship("Contact", back_populates="company", lazy="select")

    def __repr__(self) -> str:
        return f"<Company id={self.id} name={self.name!r}>"
