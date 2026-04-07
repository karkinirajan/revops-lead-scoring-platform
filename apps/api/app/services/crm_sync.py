"""HubSpot CRM sync service — batch upserts with idempotency and retry tracking."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

import httpx
import structlog

from app.config import get_settings
from app.models.audit import CrmSyncLog

logger = structlog.get_logger(__name__)
settings = get_settings()


class HubSpotSyncError(Exception):
    pass


class HubSpotClient:
    """Thin, stateless HubSpot API v3 client."""

    def __init__(self, access_token: str, base_url: str = "https://api.hubapi.com"):
        self._base_url = base_url
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self._base_url,
            headers=self._headers,
            timeout=30.0,
        )

    def batch_upsert_contacts(self, contacts: list[dict]) -> dict:
        """
        Upsert contacts by email using the HubSpot Batch API.
        contacts: list of {"email": ..., "properties": {...}}
        """
        inputs = [
            {
                "idProperty": "email",
                "id": c["email"],
                "properties": c["properties"],
            }
            for c in contacts
        ]
        with self._client() as client:
            resp = client.post("/crm/v3/objects/contacts/batch/upsert", json={"inputs": inputs})
            resp.raise_for_status()
            return resp.json()

    def batch_upsert_companies(self, companies: list[dict]) -> dict:
        """Upsert companies by domain."""
        inputs = [
            {
                "idProperty": "domain",
                "id": c["domain"],
                "properties": c["properties"],
            }
            for c in companies
            if c.get("domain")
        ]
        if not inputs:
            return {"results": []}
        with self._client() as client:
            resp = client.post("/crm/v3/objects/companies/batch/upsert", json={"inputs": inputs})
            resp.raise_for_status()
            return resp.json()

    def get_contact_by_email(self, email: str) -> dict | None:
        with self._client() as client:
            resp = client.get(f"/crm/v3/objects/contacts/{email}?idProperty=email")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()


def build_contact_sync_payload(contact_row: dict) -> dict:
    """Map internal contact + score data to HubSpot contact properties."""
    return {
        "email": contact_row["email"],
        "properties": {
            "revops_lead_score": str(contact_row.get("lead_score", "")),
            "revops_priority_tier": contact_row.get("priority_tier", ""),
            "revops_score_reason": contact_row.get("score_reason", ""),
            "revops_recommended_action": contact_row.get("recommended_action", ""),
            "revops_model_version": contact_row.get("model_version", ""),
            "revops_scored_at": contact_row.get("scored_at", ""),
        },
    }


def sync_batch_to_hubspot(
    contacts: list[dict],
    db_session,
    job_id: str | None = None,
) -> tuple[int, int]:
    """
    Sync a batch of scored contacts to HubSpot. Returns (success_count, failure_count).
    Writes CrmSyncLog entries for each outcome.
    """
    if not settings.hubspot_access_token:
        logger.warning("hubspot_access_token not configured — skipping sync")
        return 0, 0

    client = HubSpotClient(settings.hubspot_access_token, settings.hubspot_api_base_url)
    batch_size = settings.hubspot_batch_size
    success = 0
    failure = 0

    for i in range(0, len(contacts), batch_size):
        chunk = contacts[i : i + batch_size]
        payloads = [build_contact_sync_payload(c) for c in chunk]
        payload_str = json.dumps(payloads, sort_keys=True)
        payload_hash = hashlib.sha256(payload_str.encode()).hexdigest()[:16]

        try:
            _retry_with_backoff(client.batch_upsert_contacts, payloads)
            success += len(chunk)
            _log_sync(db_session, chunk, "success", None, payload_hash, job_id)
        except httpx.HTTPStatusError as exc:
            failure += len(chunk)
            logger.error(
                "hubspot_batch_upsert_failed",
                status_code=exc.response.status_code,
                chunk_size=len(chunk),
                job_id=job_id,
            )
            _log_sync(db_session, chunk, "failed", str(exc), payload_hash, job_id)
        except Exception as exc:
            failure += len(chunk)
            logger.error("hubspot_sync_error", error=str(exc), chunk_size=len(chunk))
            _log_sync(db_session, chunk, "failed", str(exc), payload_hash, job_id)

    return success, failure


def _retry_with_backoff(fn, *args, max_retries: int = 3, base_delay: float = 1.0):
    for attempt in range(max_retries):
        try:
            return fn(*args)
        except httpx.HTTPStatusError as exc:
            # 429 rate limit — always retry; 5xx server errors — retry
            if exc.response.status_code in (429, 500, 502, 503) and attempt < max_retries - 1:
                wait = base_delay * (2**attempt)
                logger.warning("hubspot_rate_limited", wait_seconds=wait, attempt=attempt + 1)
                time.sleep(wait)
            else:
                raise


def _log_sync(db_session, contacts: list[dict], status: str, error: str | None, hash_: str, job_id: str | None):
    if db_session is None:
        return
    for c in contacts:
        entry = CrmSyncLog(
            contact_id=c.get("id"),
            crm_system="hubspot",
            operation="upsert",
            status=status,
            error_message=error,
            payload_hash=hash_,
            job_id=job_id,
            synced_at=datetime.now(timezone.utc),
        )
        db_session.add(entry)
    db_session.commit()
