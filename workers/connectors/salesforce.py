"""
Salesforce connector — incremental inbound pull + outbound score push.

Inbound:
  - Pulls Contact and Lead objects modified since watermark using SOQL
  - Uses LastModifiedDate for incremental pagination
  - Normalizes to ConnectorRecord format (same interface as HubSpot connector)

Outbound:
  - Updates Lead_Score__c, Priority_Tier__c custom fields on Contacts/Leads
  - Uses Salesforce Composite API for batch updates (200 records per request)

Auth:
  - Username-Password flow (for service accounts) or
  - OAuth2 JWT Bearer flow (for production)
  - Refresh token handling included
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import httpx
import structlog

from app.security.urls import ensure_salesforce_instance_url
from workers.connectors.base import BaseConnector, ConnectorRecord

logger = structlog.get_logger(__name__)

_SF_API_VERSION = "v59.0"

# Salesforce Contact fields to pull (SOQL SELECT list)
_CONTACT_FIELDS = [
    "Id",
    "Email",
    "FirstName",
    "LastName",
    "Title",
    "AccountId",
    "LeadSource",
    "HasOptedOutOfEmail",
    "LastModifiedDate",
    "CreatedDate",
    "NumberOfEmployees__c",  # custom field example
]

# Salesforce Lead fields
_LEAD_FIELDS = [
    "Id",
    "Email",
    "FirstName",
    "LastName",
    "Title",
    "Company",
    "Industry",
    "NumberOfEmployees",
    "LeadSource",
    "Status",
    "LastModifiedDate",
    "CreatedDate",
]


class SalesforceClient:
    """Thin Salesforce REST API v59 client with auto-refresh."""

    def __init__(
        self,
        instance_url: str,
        access_token: str,
        refresh_token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ):
        self.instance_url = ensure_salesforce_instance_url(
            instance_url
        )  # the access token (and client secret) are sent here
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self._last_request = 0.0

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _throttle(self, rps: int = 25) -> None:
        elapsed = time.time() - self._last_request
        wait = (1.0 / rps) - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()

    def _refresh_access_token(self) -> None:
        if not (self.refresh_token and self.client_id and self.client_secret):
            raise RuntimeError("Cannot refresh: missing refresh_token / client credentials")

        resp = httpx.post(
            f"{self.instance_url}/services/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data["access_token"]
        logger.info("salesforce_token_refreshed")

    def _get(self, path: str, params: dict | None = None) -> dict:
        self._throttle()
        url = f"{self.instance_url}/services/data/{_SF_API_VERSION}{path}"
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, headers=self._headers(), params=params)

        if resp.status_code == 401 and self.refresh_token:
            self._refresh_access_token()
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(url, headers=self._headers(), params=params)

        resp.raise_for_status()
        return resp.json()

    def _patch_composite(self, records: list[dict]) -> dict:
        """Batch update records using the Composite API (max 200 per call)."""
        self._throttle()
        url = f"{self.instance_url}/services/data/{_SF_API_VERSION}/composite/sobjects"
        with httpx.Client(timeout=60.0) as client:
            resp = client.patch(
                url,
                headers=self._headers(),
                json={"allOrNone": False, "records": records},
            )
        resp.raise_for_status()
        return resp.json()

    def query(self, soql: str) -> list[dict]:
        """Execute a SOQL query and return all records (handles pagination)."""
        results = []
        path = "/query"
        params = {"q": soql}
        page = 0

        while True:
            data = self._get(path, params)
            results.extend(data.get("records", []))
            next_url = data.get("nextRecordsUrl")
            page += 1

            if not next_url or page > 2000:
                break

            # nextRecordsUrl is a relative path
            path = next_url.replace(f"/services/data/{_SF_API_VERSION}", "")
            params = {}

        return results

    def update_contact_scores(self, contacts: list[dict]) -> dict:
        """
        Push lead scores to Salesforce Contacts.
        contacts: [{"id": "<SF_Contact_Id>", "score": 85, "tier": "HOT"}]
        """
        records = [
            {
                "attributes": {"type": "Contact"},
                "Id": c["id"],
                "RevOps_Lead_Score__c": c.get("score"),
                "RevOps_Priority_Tier__c": c.get("tier"),
                "RevOps_Score_Reason__c": c.get("reason", "")[:255],
                "RevOps_Scored_At__c": c.get("scored_at", datetime.now(UTC).isoformat()),
            }
            for c in contacts
        ]

        results = {"success": 0, "failure": 0}
        batch_size = 200
        for i in range(0, len(records), batch_size):
            chunk = records[i : i + batch_size]
            resp = self._patch_composite(chunk)
            items: list[dict] = resp if isinstance(resp, list) else []
            for item in items:
                if item.get("success"):
                    results["success"] += 1
                else:
                    results["failure"] += 1
                    logger.warning("sf_update_failed", errors=item.get("errors"))
        return results


class SalesforceContactConnector(BaseConnector):
    """Incremental connector for Salesforce Contacts."""

    schema_version = 1

    def __init__(self, client: SalesforceClient):
        super().__init__(connector_id="salesforce_contacts")
        self.client = client

    def fetch(self, watermark: str | None) -> list[dict]:
        where = ""
        if watermark:
            where = f"WHERE LastModifiedDate > {watermark}"

        soql = f"SELECT {', '.join(_CONTACT_FIELDS)} FROM Contact {where} ORDER BY LastModifiedDate ASC LIMIT 10000"
        records = self.client.query(soql)
        logger.info("salesforce_fetched_contacts", count=len(records), watermark=watermark)
        return records

    def normalize(self, raw_record: dict) -> ConnectorRecord | None:
        email = (raw_record.get("Email") or "").lower().strip()
        if not email:
            return None

        sf_id = raw_record.get("Id", "")
        modified_str = raw_record.get("LastModifiedDate", "")

        try:
            event_time = datetime.fromisoformat(modified_str.replace("Z", "+00:00")) if modified_str else None
        except ValueError:
            event_time = None

        return ConnectorRecord(
            source_system="salesforce",
            source_record_id=sf_id,
            operation="update",
            event_time=event_time,
            schema_version=self.schema_version,
            raw_payload={
                "id": sf_id,
                "record_type": "contact",
                "properties": {
                    "email": email,
                    "firstname": raw_record.get("FirstName", ""),
                    "lastname": raw_record.get("LastName", ""),
                    "jobtitle": raw_record.get("Title", ""),
                    "salesforce_contact_id": sf_id,
                    "account_id": raw_record.get("AccountId", ""),
                    "lead_source": raw_record.get("LeadSource", ""),
                },
            },
            trace_id=str(uuid.uuid4()),
        )

    def _extract_watermark(self, records: list[dict]) -> str | None:
        timestamps = [r.get("LastModifiedDate", "") for r in records if r.get("LastModifiedDate")]
        return max(timestamps) if timestamps else None


class SalesforceSyncService:
    """Pushes lead scores back to Salesforce Contacts."""

    def __init__(self, client: SalesforceClient):
        self.client = client

    def push_scores(self, contacts: list[dict]) -> tuple[int, int]:
        """
        contacts: list of {"salesforce_id": str, "lead_score": int, "priority_tier": str, ...}
        Returns (success_count, failure_count).
        """
        sf_contacts = [
            {
                "id": c["salesforce_id"],
                "score": c["lead_score"],
                "tier": c["priority_tier"],
                "reason": c.get("score_reason", ""),
                "scored_at": c.get("scored_at", datetime.now(UTC).isoformat()),
            }
            for c in contacts
            if c.get("salesforce_id")
        ]

        if not sf_contacts:
            logger.warning("salesforce_push_no_contacts_with_sf_id")
            return 0, 0

        result = self.client.update_contact_scores(sf_contacts)
        logger.info("salesforce_scores_pushed", **result)
        return result.get("success", 0), result.get("failure", 0)
