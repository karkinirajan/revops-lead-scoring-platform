from datetime import datetime

from pydantic import Field, field_validator

from app.models.webhook import WebhookStatus
from app.schemas.common import OrmBase


class WebhookCreate(OrmBase):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(max_length=2048)
    secret: str | None = Field(default=None, min_length=16, max_length=255)  # generated when omitted
    events: str = "tier_crossed"  # comma-separated: tier_crossed,hot_lead,conversion
    tier_filter: str | None = None  # comma-separated: HOT,WARM (empty = all)

    @field_validator("events")
    @classmethod
    def validate_events(cls, v: str) -> str:
        valid = {"tier_crossed", "score_updated", "demo_requested", "hot_lead", "conversion"}
        for e in v.split(","):
            e = e.strip()
            if e and e not in valid:
                raise ValueError(f"Unknown event type: {e!r}. Valid: {sorted(valid)}")
        return v


class WebhookUpdate(OrmBase):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: str | None = Field(default=None, max_length=2048)
    secret: str | None = Field(default=None, min_length=16, max_length=255)
    events: str | None = None
    tier_filter: str | None = None
    status: WebhookStatus | None = None


class WebhookRead(OrmBase):
    id: str
    name: str
    url: str
    events: str
    tier_filter: str | None
    status: str
    total_deliveries: int
    successful_deliveries: int
    failed_deliveries: int
    last_triggered_at: datetime | None
    created_at: datetime
    # Never expose secret in reads


class WebhookCreated(WebhookRead):
    """The response to creating a webhook: the only time the signing secret is shown."""

    secret: str


class WebhookDeliveryRead(OrmBase):
    id: str
    webhook_id: str
    event_type: str
    contact_id: str | None
    status: str
    http_status_code: int | None
    response_body: str | None
    error_message: str | None
    attempt_number: int
    delivered_at: datetime | None
    created_at: datetime


class WebhookTestRequest(OrmBase):
    event_type: str = "tier_crossed"
    contact_id: str | None = None
