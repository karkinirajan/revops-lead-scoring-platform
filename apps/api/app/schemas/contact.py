from datetime import datetime

from pydantic import EmailStr

from app.schemas.common import OrmBase


class ContactCreate(OrmBase):
    source_system: str
    source_record_id: str
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    phone: str | None = None
    company_id: str | None = None
    lifecycle_stage: str | None = None
    lead_status: str | None = None
    hubspot_contact_id: str | None = None
    extra: dict | None = None


class ContactUpdate(OrmBase):
    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    phone: str | None = None
    company_id: str | None = None
    lifecycle_stage: str | None = None
    lead_status: str | None = None
    last_activity_at: datetime | None = None
    extra: dict | None = None


class ContactFeatureRead(OrmBase):
    api_calls_1d: int
    api_calls_7d: int
    api_calls_30d: int
    page_views_7d: int
    pricing_page_visited: bool
    email_opens_7d: int
    email_clicks_7d: int
    demo_requested: bool
    free_trial_active: bool
    integration_connected: bool
    integrations_count: int
    days_since_last_activity: int
    computed_at: datetime


class ContactRead(OrmBase):
    id: str
    source_system: str
    source_record_id: str
    email: str
    first_name: str | None
    last_name: str | None
    job_title: str | None
    company_id: str | None
    lifecycle_stage: str | None
    lead_status: str | None
    hubspot_contact_id: str | None
    last_activity_at: datetime | None
    created_at: datetime
    updated_at: datetime
    features: ContactFeatureRead | None = None
