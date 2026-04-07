from datetime import datetime

from app.schemas.common import OrmBase


class CompanyCreate(OrmBase):
    source_system: str
    source_record_id: str
    name: str
    domain: str | None = None
    industry: str | None = None
    employee_count: int | None = None
    annual_revenue: int | None = None
    country: str | None = None
    city: str | None = None
    size_tier: str | None = None
    lifecycle_stage: str | None = None
    hubspot_company_id: str | None = None
    extra: dict | None = None


class CompanyUpdate(OrmBase):
    name: str | None = None
    domain: str | None = None
    industry: str | None = None
    employee_count: int | None = None
    annual_revenue: int | None = None
    country: str | None = None
    city: str | None = None
    size_tier: str | None = None
    lifecycle_stage: str | None = None
    extra: dict | None = None


class CompanyRead(OrmBase):
    id: str
    source_system: str
    source_record_id: str
    name: str
    domain: str | None
    industry: str | None
    employee_count: int | None
    annual_revenue: int | None
    country: str | None
    size_tier: str | None
    hubspot_company_id: str | None
    created_at: datetime
    updated_at: datetime
