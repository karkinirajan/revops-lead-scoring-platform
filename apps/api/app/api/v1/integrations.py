"""
CRM Integrations management API.

Endpoints:
  GET    /integrations                     — list all CRM connections
  POST   /integrations                     — add a new CRM connection              (admin)
  GET    /integrations/{id}                — get connection details
  PATCH  /integrations/{id}                — update field mapping / config          (admin)
  DELETE /integrations/{id}                — remove connection                      (admin)
  POST   /integrations/{id}/sync-inbound   — trigger manual inbound pull            (analyst)
  POST   /integrations/{id}/sync-outbound  — push today's scores to CRM             (analyst)
  GET    /integrations/{id}/status         — last sync timestamps + error
  GET    /integrations/salesforce/oauth/authorize  — the Salesforce consent URL     (admin)
  POST   /integrations/salesforce/oauth/callback   — exchange the code, connect     (admin)

Connections hold CRM credentials and the URL those credentials are sent to, so creating or changing one is an admin action.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import urlencode

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth.dependencies import AdminRequired, AnalystRequired, CurrentUser, ViewerRequired
from app.auth.jwt import TokenError, decode_token, issue_token
from app.config import get_settings
from app.database import get_db
from app.models.crm_connection import CrmConnection
from app.schemas.common import OrmBase
from app.security.urls import UnsafeUrlError, ensure_salesforce_instance_url
from app.services.crm_sync import sync_batch_to_hubspot
from workers.connectors.base import BaseConnector

router = APIRouter()
logger = structlog.get_logger(__name__)

OAUTH_STATE = "salesforce_oauth_state"
OAUTH_STATE_LIFETIME = timedelta(minutes=10)

SyncDirection = Literal["inbound", "outbound", "bidirectional"]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


def _salesforce_url(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return ensure_salesforce_instance_url(value)
    except UnsafeUrlError as exc:
        raise ValueError(f"instance_url: {exc}") from None


class CrmConnectionCreate(OrmBase):
    crm_type: Literal["hubspot", "salesforce"]
    name: str = Field(min_length=1, max_length=255)
    org_id: str | None = Field(default=None, max_length=100)
    access_token: str = Field(min_length=1)
    refresh_token: str | None = None
    instance_url: str | None = Field(default=None, max_length=500)  # required for Salesforce
    sync_direction: SyncDirection = "bidirectional"
    score_field_name: str = Field(default="revops_lead_score", max_length=100)
    tier_field_name: str = Field(default="revops_priority_tier", max_length=100)
    field_mapping: dict | None = None

    @field_validator("instance_url")
    @classmethod
    def _instance_url_is_salesforce(cls, value: str | None) -> str | None:
        return _salesforce_url(value)


class CrmConnectionUpdate(OrmBase):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    sync_direction: SyncDirection | None = None
    score_field_name: str | None = Field(default=None, max_length=100)
    tier_field_name: str | None = Field(default=None, max_length=100)
    field_mapping: dict | None = None
    access_token: str | None = Field(default=None, min_length=1)
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
    # access_token and refresh_token are intentionally omitted


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


def _get_or_404(db: Session, conn_id: str) -> CrmConnection:
    conn = db.get(CrmConnection, conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Integration not found")
    return conn


@router.get("", response_model=list[CrmConnectionRead], dependencies=[ViewerRequired])
def list_integrations(db: Annotated[Session, Depends(get_db)]):
    return db.scalars(select(CrmConnection).order_by(CrmConnection.created_at.desc())).all()


@router.post("", response_model=CrmConnectionRead, status_code=status.HTTP_201_CREATED, dependencies=[AdminRequired])
def create_integration(
    body: CrmConnectionCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
):
    if body.crm_type == "salesforce" and not body.instance_url:
        raise HTTPException(status_code=400, detail="instance_url required for Salesforce")
    if body.crm_type == "hubspot" and body.instance_url:
        raise HTTPException(status_code=400, detail="instance_url is only used for Salesforce")

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
    return _get_or_404(db, conn_id)


@router.patch("/{conn_id}", response_model=CrmConnectionRead, dependencies=[AdminRequired])
def update_integration(conn_id: str, body: CrmConnectionUpdate, db: Annotated[Session, Depends(get_db)]):
    conn = _get_or_404(db, conn_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None and field in (
            "name",
            "is_active",
            "sync_direction",
            "score_field_name",
            "tier_field_name",
            "access_token",
        ):
            continue  # these cannot be cleared
        setattr(conn, field, value)
    db.commit()
    db.refresh(conn)
    return conn


@router.delete("/{conn_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[AdminRequired])
def delete_integration(conn_id: str, db: Annotated[Session, Depends(get_db)]):
    db.delete(_get_or_404(db, conn_id))
    db.commit()


@router.get("/{conn_id}/status", dependencies=[ViewerRequired])
def integration_status(conn_id: str, db: Annotated[Session, Depends(get_db)]):
    conn = _get_or_404(db, conn_id)
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


def _salesforce_client(conn: CrmConnection):
    from workers.connectors.salesforce import SalesforceClient

    settings = get_settings()
    return SalesforceClient(
        instance_url=conn.instance_url or "",
        access_token=conn.access_token or "",
        refresh_token=conn.refresh_token,
        client_id=settings.salesforce_client_id or None,
        client_secret=settings.salesforce_client_secret or None,
    )


@router.post("/{conn_id}/sync-inbound", response_model=SyncResult, dependencies=[AnalystRequired])
def sync_inbound(conn_id: str, db: Annotated[Session, Depends(get_db)]):
    """Trigger an incremental inbound pull for this CRM connection."""
    conn = _get_or_404(db, conn_id)
    if not conn.is_active:
        raise HTTPException(status_code=409, detail="Integration is disabled")

    start = time.time()
    records_processed = 0
    success = 0
    failure = 0

    try:
        connector: BaseConnector
        if conn.crm_type == "salesforce":
            from workers.connectors.salesforce import SalesforceContactConnector

            connector = SalesforceContactConnector(_salesforce_client(conn))
        else:
            from workers.connectors.hubspot import HubSpotConnector

            connector = HubSpotConnector(access_token=conn.access_token or "", portal_id=conn.org_id or "")

        # run() = fetch since the last checkpoint, normalize, publish to the ingest queue, save the new checkpoint
        summary = connector.run()
        success = int(summary["published"])
        records_processed = success + int(summary["skipped"])

        conn.last_inbound_sync_at = datetime.now(UTC)
        conn.last_sync_error = None
        db.commit()

    except Exception as exc:
        db.rollback()
        conn = _get_or_404(db, conn_id)
        conn.last_sync_error = str(exc)[:500]
        db.commit()
        failure = 1
        logger.error("inbound_sync_error", conn_id=conn_id, error=str(exc))

    return SyncResult(
        direction="inbound",
        records_processed=records_processed,
        success=success,
        failure=failure,
        duration_seconds=round(time.time() - start, 2),
        synced_at=datetime.now(UTC),
    )


@router.post("/{conn_id}/sync-outbound", response_model=SyncResult, dependencies=[AnalystRequired])
def sync_outbound(conn_id: str, db: Annotated[Session, Depends(get_db)]):
    """Push today's scored leads to this CRM connection."""
    conn = _get_or_404(db, conn_id)
    if not conn.is_active:
        raise HTTPException(status_code=409, detail="Integration is disabled")

    start = time.time()

    # Top HOT/WARM leads scored in the last 24h. A Salesforce push needs the Salesforce Contact Id, which is the source record id of contacts that came
    # from Salesforce; a HubSpot id is not one.
    rows = db.execute(
        text(
            """
            SELECT c.email, c.hubspot_contact_id, ls.lead_score, ls.priority_tier, ls.score_reason, ls.scored_at,
                   c.source_system, c.source_record_id
            FROM lead_scores ls
            JOIN contacts c ON ls.contact_id = c.id
            WHERE ls.is_shadow = false
              AND ls.scored_at >= NOW() - INTERVAL '24 hours'
              AND ls.priority_tier IN ('HOT', 'WARM')
            ORDER BY ls.lead_score DESC
            LIMIT 500
            """
        )
    ).fetchall()

    contacts = [
        {
            "email": r[0],
            "hubspot_id": r[1],
            "lead_score": r[2],
            "priority_tier": r[3],
            "score_reason": r[4] or "",
            "scored_at": r[5].isoformat() if r[5] else "",
            "source_system": r[6],
            "source_record_id": r[7],
        }
        for r in rows
    ]

    success, failure = 0, 0

    if conn.crm_type == "hubspot":
        success, failure = sync_batch_to_hubspot(contacts, db_session=db)
    elif conn.crm_type == "salesforce":
        from workers.connectors.salesforce import SalesforceSyncService

        salesforce_contacts = [
            {**c, "salesforce_id": c["source_record_id"]} for c in contacts if c["source_system"] == "salesforce"
        ]
        try:
            client = _salesforce_client(conn)
        except UnsafeUrlError as exc:
            raise HTTPException(
                status_code=409, detail=f"This connection's instance_url is not usable: {exc}"
            ) from None
        success, failure = SalesforceSyncService(client).push_scores(salesforce_contacts)
        contacts = salesforce_contacts

    conn.last_outbound_sync_at = datetime.now(UTC)
    conn.total_records_synced += success
    db.commit()

    return SyncResult(
        direction="outbound",
        records_processed=len(contacts),
        success=success,
        failure=failure,
        duration_seconds=round(time.time() - start, 2),
        synced_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Salesforce OAuth 2.0 (authorization code)
# ---------------------------------------------------------------------------


def _salesforce_oauth_settings():
    settings = get_settings()
    if not (settings.salesforce_client_id and settings.salesforce_client_secret and settings.salesforce_redirect_uri):
        raise HTTPException(
            status_code=503,
            detail="Salesforce OAuth not configured. Set SALESFORCE_CLIENT_ID, SALESFORCE_CLIENT_SECRET, SALESFORCE_REDIRECT_URI.",
        )
    try:
        ensure_salesforce_instance_url(settings.salesforce_login_url)
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=503, detail=f"SALESFORCE_LOGIN_URL is not usable: {exc}") from None
    return settings


@router.get("/salesforce/oauth/authorize", dependencies=[AdminRequired])
def salesforce_oauth_authorize(current_user: CurrentUser):
    """The URL to send the admin to for Salesforce consent. Its `state` is signed, expires in ten minutes and is tied to this user."""
    settings = _salesforce_oauth_settings()
    state = issue_token(current_user.id, OAUTH_STATE, OAUTH_STATE_LIFETIME, None)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.salesforce_client_id,
            "redirect_uri": settings.salesforce_redirect_uri,
            "state": state,
        }
    )
    return {"authorize_url": f"{settings.salesforce_login_url.rstrip('/')}/services/oauth2/authorize?{query}"}


@router.post("/salesforce/oauth/callback", status_code=status.HTTP_201_CREATED, dependencies=[AdminRequired])
def salesforce_oauth_callback(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    code: str = Query(..., min_length=1, max_length=2048),
    state: str = Query(..., min_length=1, max_length=4096),
):
    """Exchange the authorization code for tokens and create the connection. The `state` must be one this user was given by /authorize."""
    settings = _salesforce_oauth_settings()
    try:
        claims = decode_token(state, OAUTH_STATE)
    except TokenError:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state") from None
    if claims["sub"] != current_user.id:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    resp = httpx.post(
        f"{settings.salesforce_login_url.rstrip('/')}/services/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": settings.salesforce_client_id,
            "client_secret": settings.salesforce_client_secret,
            "redirect_uri": settings.salesforce_redirect_uri,
            "code": code,
        },
        timeout=30.0,
        follow_redirects=False,
    )
    if not resp.is_success:
        logger.warning("salesforce_oauth_failed", status=resp.status_code)
        raise HTTPException(status_code=400, detail="Salesforce rejected the authorization code")

    token_data = resp.json()
    try:
        instance_url = ensure_salesforce_instance_url(token_data.get("instance_url", ""))
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=502, detail=f"Salesforce returned an unusable instance_url: {exc}") from None

    # the identity URL is https://login.salesforce.com/id/<org id>/<user id>
    identity_parts = (token_data.get("id") or "").rstrip("/").split("/")
    org_id = identity_parts[-2] if len(identity_parts) >= 2 else None

    conn = CrmConnection(
        crm_type="salesforce",
        name=f"Salesforce ({instance_url})",
        org_id=org_id,
        access_token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        instance_url=instance_url,
        created_by=current_user.id,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    logger.info("salesforce_oauth_connected", org_id=conn.org_id)
    return {"status": "connected", "connection_id": conn.id, "instance_url": instance_url}
