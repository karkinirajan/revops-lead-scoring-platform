"""
CRM Integrations management API.

Endpoints:
  GET    /integrations                     — list all CRM connections
  POST   /integrations                     — add a new CRM connection
  GET    /integrations/{id}                — get connection details
  PATCH  /integrations/{id}                — update field mapping / config
  DELETE /integrations/{id}                — remove connection
  POST   /integrations/{id}/sync-inbound   — trigger manual inbound pull
  POST   /integrations/{id}/sync-outbound  — push today's scores to CRM
  GET    /integrations/{id}/status         — last sync timestamps + error
  POST   /integrations/salesforce/oauth/callback  — Salesforce OAuth callback
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import AdminRequired, AnalystRequired, CurrentUser, ViewerRequired
from app.database import get_db
from app.models.crm_connection import CrmConnection
from app.schemas.common import OrmBase

router = APIRouter()
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CrmConnectionCreate(OrmBase):
    crm_type: str                              # hubspot | salesforce
    name: str
    org_id: str | None = None
    access_token: str
    refresh_token: str | None = None
    instance_url: str | None = None            # required for Salesforce
    sync_direction: str = "bidirectional"
    score_field_name: str = "revops_lead_score"
    tier_field_name: str = "revops_priority_tier"
    field_mapping: dict | None = None


class CrmConnectionUpdate(OrmBase):
    name: str | None = None
    is_active: bool | None = None
    sync_direction: str | None = None
    score_field_name: str | None = None
    tier_field_name: str | None = None
    field_mapping: dict | None = None
    access_token: str | None = None
    refresh_token: str | None = None


class CrmConnectionRead(OrmBase):
    id: str
    crm_type: str
    name: str
    org_id: str | None
    instance_url: str | None
    is_active: bool
    sync_direction: str
    score_field_name: str
    tier_field_name: str
    field_mapping: dict | None
    last_inbound_sync_at: datetime | None
    last_outbound_sync_at: datetime | None
    last_sync_error: str | None
    total_records_synced: int
    created_at: datetime
    # access_token intentionally omitted


class SyncResult(OrmBase):
    direction: str
    records_processed: int
    success: int
    failure: int
    duration_seconds: float
    synced_at: datetime


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[CrmConnectionRead], dependencies=[ViewerRequired])
def list_integrations(db: Annotated[Session, Depends(get_db)]):
    return db.scalars(select(CrmConnection).order_by(CrmConnection.created_at.desc())).all()


@router.post("", response_model=CrmConnectionRead, status_code=status.HTTP_201_CREATED)
def create_integration(
    body: CrmConnectionCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
):
    if body.crm_type not in ("hubspot", "salesforce"):
        raise HTTPException(status_code=400, detail="crm_type must be 'hubspot' or 'salesforce'")
    if body.crm_type == "salesforce" and not body.instance_url:
        raise HTTPException(status_code=400, detail="instance_url required for Salesforce")

    conn = CrmConnection(
        crm_type=body.crm_type,
        name=body.name,
        org_id=body.org_id,
        access_token=body.access_token,
        refresh_token=body.refresh_token,
        instance_url=body.instance_url,
        sync_direction=body.sync_direction,
        score_field_name=body.score_field_name,
        tier_field_name=body.tier_field_name,
        field_mapping=body.field_mapping,
        created_by=current_user.id,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    logger.info("crm_connection_created", crm_type=body.crm_type, name=body.name)
    return conn


@router.get("/{conn_id}", response_model=CrmConnectionRead, dependencies=[ViewerRequired])
def get_integration(conn_id: str, db: Annotated[Session, Depends(get_db)]):
    conn = db.get(CrmConnection, conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Integration not found")
    return conn


@router.patch("/{conn_id}", response_model=CrmConnectionRead)
def update_integration(
    conn_id: str,
    body: CrmConnectionUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
):
    conn = db.get(CrmConnection, conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Integration not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(conn, field, value)
    db.commit()
    db.refresh(conn)
    return conn


@router.delete("/{conn_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[AdminRequired])
def delete_integration(conn_id: str, db: Annotated[Session, Depends(get_db)]):
    conn = db.get(CrmConnection, conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Integration not found")
    db.delete(conn)
    db.commit()


@router.get("/{conn_id}/status", dependencies=[ViewerRequired])
def integration_status(conn_id: str, db: Annotated[Session, Depends(get_db)]):
    conn = db.get(CrmConnection, conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Integration not found")
    return {
        "id": conn.id,
        "crm_type": conn.crm_type,
        "name": conn.name,
        "is_active": conn.is_active,
        "last_inbound_sync_at": conn.last_inbound_sync_at,
        "last_outbound_sync_at": conn.last_outbound_sync_at,
        "last_sync_error": conn.last_sync_error,
        "total_records_synced": conn.total_records_synced,
    }


@router.post("/{conn_id}/sync-inbound", response_model=SyncResult, dependencies=[AnalystRequired])
def sync_inbound(conn_id: str, db: Annotated[Session, Depends(get_db)]):
    """Trigger an incremental inbound pull for this CRM connection."""
    import time
    conn = db.get(CrmConnection, conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Integration not found")
    if not conn.is_active:
        raise HTTPException(status_code=409, detail="Integration is disabled")

    start = time.time()
    records_processed = 0
    success = 0
    failure = 0

    try:
        if conn.crm_type == "salesforce":
            from workers.connectors.salesforce import SalesforceClient, SalesforceContactConnector
            client = SalesforceClient(
                instance_url=conn.instance_url or "",
                access_token=conn.access_token or "",
                refresh_token=conn.refresh_token,
            )
            connector = SalesforceContactConnector(client)
            raw_records = connector.fetch(watermark=None)
            records_processed = len(raw_records)
            success = records_processed
        elif conn.crm_type == "hubspot":
            # Dispatch Celery task for background pull
            try:
                from workers.tasks.ingest import run_hubspot_connector
                run_hubspot_connector.delay()
                records_processed = -1  # async — actual count unknown
            except Exception:
                records_processed = 0

        conn.last_inbound_sync_at = datetime.now(timezone.utc)
        conn.last_sync_error = None
        db.commit()

    except Exception as exc:
        conn.last_sync_error = str(exc)[:500]
        db.commit()
        failure = 1
        logger.error("inbound_sync_error", conn_id=conn_id, error=str(exc))

    duration = time.time() - start
    return SyncResult(
        direction="inbound",
        records_processed=records_processed,
        success=success,
        failure=failure,
        duration_seconds=round(duration, 2),
        synced_at=datetime.now(timezone.utc),
    )


@router.post("/{conn_id}/sync-outbound", response_model=SyncResult, dependencies=[AnalystRequired])
def sync_outbound(conn_id: str, db: Annotated[Session, Depends(get_db)]):
    """Push today's scored leads to this CRM connection."""
    import time
    conn = db.get(CrmConnection, conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Integration not found")
    if not conn.is_active:
        raise HTTPException(status_code=409, detail="Integration is disabled")

    start = time.time()

    from sqlalchemy import func, text
    # Get top HOT/WARM leads scored in last 24h
    rows = db.execute(
        text("""
            SELECT c.email, c.hubspot_contact_id, ls.lead_score, ls.priority_tier, ls.score_reason, ls.scored_at
            FROM lead_scores ls
            JOIN contacts c ON ls.contact_id = c.id
            WHERE ls.is_shadow = false
              AND ls.scored_at >= NOW() - INTERVAL '24 hours'
              AND ls.priority_tier IN ('HOT', 'WARM')
            ORDER BY ls.lead_score DESC
            LIMIT 500
        """)
    ).fetchall()

    contacts = [
        {
            "email": r[0],
            "hubspot_id": r[1],
            "lead_score": r[2],
            "priority_tier": r[3],
            "score_reason": r[4] or "",
            "scored_at": r[5].isoformat() if r[5] else "",
        }
        for r in rows
    ]

    success, failure = 0, 0

    if conn.crm_type == "hubspot":
        from app.services.crm_sync import sync_batch_to_hubspot
        success, failure = sync_batch_to_hubspot(contacts, db_session=db)
    elif conn.crm_type == "salesforce":
        from workers.connectors.salesforce import SalesforceClient, SalesforceSyncService
        client = SalesforceClient(
            instance_url=conn.instance_url or "",
            access_token=conn.access_token or "",
            refresh_token=conn.refresh_token,
        )
        svc = SalesforceSyncService(client)
        sf_contacts = [
            {**c, "salesforce_id": c.get("hubspot_id")}  # reuse ID field
            for c in contacts
        ]
        success, failure = svc.push_scores(sf_contacts)

    conn.last_outbound_sync_at = datetime.now(timezone.utc)
    conn.total_records_synced += success
    db.commit()

    duration = time.time() - start
    return SyncResult(
        direction="outbound",
        records_processed=len(contacts),
        success=success,
        failure=failure,
        duration_seconds=round(duration, 2),
        synced_at=datetime.now(timezone.utc),
    )


@router.post("/salesforce/oauth/callback")
async def salesforce_oauth_callback(
    code: str = Query(...),
    state: str | None = Query(None),
    db: Annotated[Session, Depends(get_db)] = None,
):
    """
    Handle Salesforce OAuth 2.0 authorization_code callback.
    Exchange the code for access + refresh tokens, create a CrmConnection.
    """
    from app.config import get_settings
    settings = get_settings()

    sf_client_id     = getattr(settings, "salesforce_client_id", "")
    sf_client_secret = getattr(settings, "salesforce_client_secret", "")
    sf_redirect_uri  = getattr(settings, "salesforce_redirect_uri", "")

    if not (sf_client_id and sf_client_secret and sf_redirect_uri):
        raise HTTPException(
            status_code=503,
            detail="Salesforce OAuth not configured. Set SALESFORCE_CLIENT_ID, SALESFORCE_CLIENT_SECRET, SALESFORCE_REDIRECT_URI.",
        )

    import httpx
    resp = httpx.post(
        "https://login.salesforce.com/services/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": sf_client_id,
            "client_secret": sf_client_secret,
            "redirect_uri": sf_redirect_uri,
            "code": code,
        },
        timeout=30.0,
    )
    if not resp.is_success:
        raise HTTPException(status_code=400, detail=f"Salesforce OAuth error: {resp.text[:300]}")

    token_data = resp.json()
    instance_url = token_data.get("instance_url", "")

    conn = CrmConnection(
        crm_type="salesforce",
        name=f"Salesforce ({instance_url})",
        org_id=token_data.get("id", "").split("/")[-1],
        access_token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        instance_url=instance_url,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    logger.info("salesforce_oauth_connected", org_id=conn.org_id)
    return {"status": "connected", "connection_id": conn.id, "instance_url": instance_url}
