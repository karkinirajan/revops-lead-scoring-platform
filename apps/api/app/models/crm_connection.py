"""CRM connection configs — OAuth tokens and field mapping per integration."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CrmConnection(Base):
    """
    Stores one connected CRM instance (HubSpot portal or Salesforce org).

    OAuth tokens are stored encrypted in production.
    Field mapping config maps CRM field API names to internal ContactFeature columns.
    """

    __tablename__ = "crm_connections"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Identity
    crm_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)  # hubspot | salesforce
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    org_id: Mapped[str | None] = mapped_column(String(100), index=True)  # HubSpot portal ID or Salesforce org ID

    # Auth
    access_token: Mapped[str | None] = mapped_column(Text)     # should be encrypted at rest
    refresh_token: Mapped[str | None] = mapped_column(Text)    # for OAuth refresh
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    instance_url: Mapped[str | None] = mapped_column(String(500))  # Salesforce: https://xxx.salesforce.com

    # Sync config
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    sync_direction: Mapped[str] = mapped_column(String(20), default="bidirectional")  # inbound | outbound | bidirectional
    score_field_name: Mapped[str] = mapped_column(String(100), default="revops_lead_score")
    tier_field_name: Mapped[str] = mapped_column(String(100), default="revops_priority_tier")

    # Field mapping: CRM API field name → internal ContactFeature column
    field_mapping: Mapped[dict | None] = mapped_column(JSONB)

    # Sync state
    last_inbound_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_outbound_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    total_records_synced: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
