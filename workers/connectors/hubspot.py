"""
HubSpot connector — pulls contacts, companies, and engagements
using HubSpot's v3 CRM API with cursor-based pagination.

Supports:
  - Incremental pull via `updatedAfter` filter
  - Full backfill when no watermark is set
  - Rate-limit aware (10 req/s default)
  - Quarantine for missing required fields
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

import httpx
import structlog

from workers.connectors.base import BaseConnector, ConnectorRecord

logger = structlog.get_logger(__name__)

# HubSpot contact properties to request
_CONTACT_PROPS = [
    "email", "firstname", "lastname", "jobtitle", "phone",
    "company", "domain", "lifecyclestage", "hs_lead_status",
    "hubspot_owner_id", "lastmodifieddate", "createdate",
]

# HubSpot company properties to request
_COMPANY_PROPS = [
    "name", "domain", "industry", "numberofemployees",
    "annualrevenue", "country", "city", "lifecyclestage",
    "hubspot_owner_id", "hs_lastmodifieddate",
]


class HubSpotConnector(BaseConnector):
    """Incremental connector for HubSpot CRM contacts and companies."""

    schema_version = 1

    def __init__(self, access_token: str, portal_id: str = "", rate_limit_per_second: int = 10):
        super().__init__(connector_id="hubspot_contacts")
        self.access_token = access_token
        self.portal_id = portal_id
        self._rate_limit = rate_limit_per_second
        self._last_request_time = 0.0

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _throttle(self):
        """Respect the rate limit between API calls."""
        elapsed = time.time() - self._last_request_time
        wait = (1.0 / self._rate_limit) - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_time = time.time()

    def fetch(self, watermark: str | None) -> list[dict]:
        """
        Fetch all contacts modified since the watermark (ISO datetime string).
        Returns raw HubSpot contact objects.
        """
        contacts = self._fetch_contacts(watermark)
        logger.info("hubspot_fetched", count=len(contacts), watermark=watermark)
        return contacts

    def _fetch_contacts(self, watermark: str | None) -> list[dict]:
        """Page through HubSpot contacts API, optionally filtered by updatedAfter."""
        results = []
        after: str | None = None
        page_count = 0

        while True:
            self._throttle()
            params: dict = {
                "limit": 100,
                "properties": ",".join(_CONTACT_PROPS),
            }
            if after:
                params["after"] = after
            if watermark:
                # HubSpot search endpoint supports date filtering
                return self._search_contacts_since(watermark)

            try:
                with httpx.Client(headers=self._headers(), timeout=30.0) as client:
                    resp = client.get("https://api.hubapi.com/crm/v3/objects/contacts", params=params)
                    resp.raise_for_status()
                    data = resp.json()
            except httpx.HTTPStatusError as exc:
                logger.error("hubspot_api_error", status=exc.response.status_code, detail=exc.response.text[:200])
                raise

            results.extend(data.get("results", []))
            paging = data.get("paging", {})
            next_page = paging.get("next", {}).get("after")
            page_count += 1

            if not next_page or page_count > 1000:  # safety cap
                break
            after = next_page

        return results

    def _search_contacts_since(self, watermark: str) -> list[dict]:
        """Use HubSpot Search API to get contacts updated after watermark."""
        results = []
        after: str | None = None

        while True:
            self._throttle()
            body: dict = {
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": "lastmodifieddate",
                                "operator": "GT",
                                "value": watermark,
                            }
                        ]
                    }
                ],
                "properties": _CONTACT_PROPS,
                "limit": 100,
            }
            if after:
                body["after"] = after

            try:
                with httpx.Client(headers=self._headers(), timeout=30.0) as client:
                    resp = client.post("https://api.hubapi.com/crm/v3/objects/contacts/search", json=body)
                    resp.raise_for_status()
                    data = resp.json()
            except httpx.HTTPStatusError as exc:
                logger.error("hubspot_search_error", status=exc.response.status_code)
                raise

            results.extend(data.get("results", []))
            paging = data.get("paging", {})
            next_after = paging.get("next", {}).get("after")
            if not next_after:
                break
            after = next_after

        return results

    def normalize(self, raw_record: dict) -> ConnectorRecord | None:
        """Map a HubSpot contact record to a ConnectorRecord envelope."""
        props = raw_record.get("properties", {})
        email = props.get("email", "").lower().strip()

        if not email:
            logger.debug("hubspot_contact_no_email", hs_id=raw_record.get("id"))
            return None  # quarantine — no email

        hs_id = raw_record.get("id", "")
        modified_str = props.get("lastmodifieddate", "")

        try:
            event_time = datetime.fromisoformat(modified_str.replace("Z", "+00:00")) if modified_str else None
        except ValueError:
            event_time = None

        return ConnectorRecord(
            source_system="hubspot",
            source_record_id=hs_id,
            operation="update" if modified_str else "insert",
            event_time=event_time,
            schema_version=self.schema_version,
            raw_payload={
                "id": hs_id,
                "properties": {
                    "email": email,
                    "firstname": props.get("firstname", ""),
                    "lastname": props.get("lastname", ""),
                    "jobtitle": props.get("jobtitle", ""),
                    "phone": props.get("phone", ""),
                    "company": props.get("company", ""),
                    "domain": props.get("domain", ""),
                    "lifecyclestage": props.get("lifecyclestage", ""),
                    "lead_status": props.get("hs_lead_status", ""),
                    "hubspot_owner_id": props.get("hubspot_owner_id", ""),
                },
            },
            trace_id=str(uuid.uuid4()),
        )

    def _extract_watermark(self, records: list[dict]) -> str | None:
        """Return the latest lastmodifieddate from the batch as the new watermark."""
        timestamps = []
        for r in records:
            ts = r.get("properties", {}).get("lastmodifieddate", "")
            if ts:
                timestamps.append(ts)
        return max(timestamps) if timestamps else None


class HubSpotCompanyConnector(BaseConnector):
    """Incremental connector for HubSpot companies."""

    schema_version = 1

    def __init__(self, access_token: str, rate_limit_per_second: int = 10):
        super().__init__(connector_id="hubspot_companies")
        self.access_token = access_token
        self._rate_limit = rate_limit_per_second
        self._last_request_time = 0.0

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

    def _throttle(self):
        elapsed = time.time() - self._last_request_time
        wait = (1.0 / self._rate_limit) - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_time = time.time()

    def fetch(self, watermark: str | None) -> list[dict]:
        results = []
        after = None
        page_count = 0

        while True:
            self._throttle()
            params: dict = {"limit": 100, "properties": ",".join(_COMPANY_PROPS)}
            if after:
                params["after"] = after

            with httpx.Client(headers=self._headers(), timeout=30.0) as client:
                resp = client.get("https://api.hubapi.com/crm/v3/objects/companies", params=params)
                resp.raise_for_status()
                data = resp.json()

            results.extend(data.get("results", []))
            next_page = data.get("paging", {}).get("next", {}).get("after")
            page_count += 1
            if not next_page or page_count > 500:
                break
            after = next_page

        return results

    def normalize(self, raw_record: dict) -> ConnectorRecord | None:
        props = raw_record.get("properties", {})
        name = props.get("name", "").strip()
        if not name:
            return None

        hs_id = raw_record.get("id", "")
        return ConnectorRecord(
            source_system="hubspot",
            source_record_id=f"company:{hs_id}",
            operation="update",
            event_time=None,
            schema_version=self.schema_version,
            raw_payload={
                "id": hs_id,
                "record_type": "company",
                "properties": {
                    "name": name,
                    "domain": props.get("domain", ""),
                    "industry": props.get("industry", ""),
                    "employee_count": props.get("numberofemployees", ""),
                    "annual_revenue": props.get("annualrevenue", ""),
                    "country": props.get("country", ""),
                    "city": props.get("city", ""),
                    "hubspot_company_id": hs_id,
                },
            },
            trace_id=str(uuid.uuid4()),
        )
