"""
Webhook management API.

Endpoints:
  GET    /webhooks                       — list all webhooks
  POST   /webhooks                       — register a new webhook
  GET    /webhooks/{id}                  — get webhook details
  PATCH  /webhooks/{id}                  — update webhook
  DELETE /webhooks/{id}                  — remove webhook
  GET    /webhooks/{id}/deliveries       — delivery history
  POST   /webhooks/{id}/test             — send a test ping
  POST   /webhooks/{id}/deliveries/{did}/retry  — manually retry a delivery
"""
from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import AdminRequired, AnalystRequired, CurrentUser, ViewerRequired
from app.database import get_db
from app.models.webhook import Webhook, WebhookDeliveryLog, WebhookStatus
from app.schemas.common import PaginatedResponse
from app.schemas.webhook import (
    WebhookCreate,
    WebhookDeliveryRead,
    WebhookRead,
    WebhookTestRequest,
    WebhookUpdate,
)
from app.services.webhook_service import build_payload, dispatch_event, retry_failed_delivery

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("", response_model=list[WebhookRead], dependencies=[ViewerRequired])
def list_webhooks(db: Annotated[Session, Depends(get_db)]):
    return db.scalars(select(Webhook).order_by(Webhook.created_at.desc())).all()


@router.post("", response_model=WebhookRead, status_code=status.HTTP_201_CREATED)
def create_webhook(
    body: WebhookCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
):
    hook = Webhook(
        name=body.name,
        url=body.url,
        secret=body.secret,
        events=body.events,
        tier_filter=body.tier_filter,
        created_by=current_user.id,
    )
    db.add(hook)
    db.commit()
    db.refresh(hook)
    logger.info("webhook_created", id=hook.id, url=hook.url, events=hook.events)
    return hook


@router.get("/{webhook_id}", response_model=WebhookRead, dependencies=[ViewerRequired])
def get_webhook(webhook_id: str, db: Annotated[Session, Depends(get_db)]):
    hook = db.get(Webhook, webhook_id)
    if not hook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return hook


@router.patch("/{webhook_id}", response_model=WebhookRead)
def update_webhook(
    webhook_id: str,
    body: WebhookUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
):
    hook = db.get(Webhook, webhook_id)
    if not hook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(hook, field, value)
    db.commit()
    db.refresh(hook)
    return hook


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[AnalystRequired])
def delete_webhook(webhook_id: str, db: Annotated[Session, Depends(get_db)]):
    hook = db.get(Webhook, webhook_id)
    if not hook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    db.delete(hook)
    db.commit()


@router.get("/{webhook_id}/deliveries", response_model=PaginatedResponse[WebhookDeliveryRead],
            dependencies=[ViewerRequired])
def list_deliveries(
    webhook_id: str,
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
):
    hook = db.get(Webhook, webhook_id)
    if not hook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    from sqlalchemy import func
    q = select(WebhookDeliveryLog).where(
        WebhookDeliveryLog.webhook_id == webhook_id
    ).order_by(WebhookDeliveryLog.created_at.desc())

    if status_filter:
        q = q.where(WebhookDeliveryLog.status == status_filter)

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    items = db.scalars(q.offset((page - 1) * page_size).limit(page_size)).all()
    return PaginatedResponse(
        items=list(items),
        total=total or 0,
        page=page,
        page_size=page_size,
        pages=max(1, -(-(total or 0) // page_size)),
    )


@router.post("/{webhook_id}/test", status_code=status.HTTP_200_OK)
def test_webhook(
    webhook_id: str,
    body: WebhookTestRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
):
    """Send a test ping to the webhook endpoint."""
    hook = db.get(Webhook, webhook_id)
    if not hook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    count = dispatch_event(
        db=db,
        event_type=body.event_type,
        contact_id=body.contact_id,
        data={"test": True, "triggered_by": current_user.email},
        async_mode=False,  # deliver synchronously for test
    )
    return {"status": "sent", "delivered_to": count}


@router.post("/{webhook_id}/deliveries/{delivery_id}/retry", status_code=status.HTTP_200_OK,
             dependencies=[AnalystRequired])
def retry_delivery(
    webhook_id: str,
    delivery_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    log_entry = db.get(WebhookDeliveryLog, delivery_id)
    if not log_entry or log_entry.webhook_id != webhook_id:
        raise HTTPException(status_code=404, detail="Delivery log not found")

    retried = retry_failed_delivery(db, delivery_id)
    if not retried:
        raise HTTPException(status_code=409, detail="Cannot retry: max attempts reached or already successful")
    return {"status": "retried"}
