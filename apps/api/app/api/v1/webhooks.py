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

import secrets
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import AnalystRequired, CurrentUser, ViewerRequired
from app.database import get_db
from app.models.webhook import Webhook, WebhookDeliveryLog
from app.schemas.common import PaginatedResponse
from app.schemas.webhook import (
    WebhookCreate,
    WebhookCreated,
    WebhookDeliveryRead,
    WebhookRead,
    WebhookTestRequest,
    WebhookUpdate,
)
from app.security.urls import UnsafeUrlError, ensure_public_url
from app.services.webhook_service import retry_failed_delivery, send_test_delivery

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("", response_model=list[WebhookRead], dependencies=[ViewerRequired])
def list_webhooks(db: Annotated[Session, Depends(get_db)]):
    return db.scalars(select(Webhook).order_by(Webhook.created_at.desc())).all()


def _checked_url(url: str) -> str:
    """A webhook target must be a public http(s) address: the server will call it."""
    try:
        return ensure_public_url(url)
    except UnsafeUrlError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Invalid webhook URL: {exc}"
        ) from None


@router.post("", response_model=WebhookCreated, status_code=status.HTTP_201_CREATED, dependencies=[AnalystRequired])
def create_webhook(
    body: WebhookCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
):
    hook = Webhook(
        name=body.name,
        url=_checked_url(body.url),
        secret=body.secret or secrets.token_urlsafe(32),
        events=body.events,
        tier_filter=body.tier_filter,
        created_by=current_user.id,
    )
    db.add(hook)
    db.commit()
    db.refresh(hook)
    logger.info("webhook_created", id=hook.id, events=hook.events)
    return hook


@router.get("/{webhook_id}", response_model=WebhookRead, dependencies=[ViewerRequired])
def get_webhook(webhook_id: str, db: Annotated[Session, Depends(get_db)]):
    hook = db.get(Webhook, webhook_id)
    if not hook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return hook


@router.patch("/{webhook_id}", response_model=WebhookRead, dependencies=[AnalystRequired])
def update_webhook(
    webhook_id: str,
    body: WebhookUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
):
    hook = db.get(Webhook, webhook_id)
    if not hook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    changes = body.model_dump(exclude_unset=True)
    if changes.get("url") is not None:
        changes["url"] = _checked_url(changes["url"])
    for field, value in changes.items():
        if value is None and field in ("name", "url", "status"):  # these cannot be cleared
            continue
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


@router.get(
    "/{webhook_id}/deliveries", response_model=PaginatedResponse[WebhookDeliveryRead], dependencies=[ViewerRequired]
)
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

    q = (
        select(WebhookDeliveryLog)
        .where(WebhookDeliveryLog.webhook_id == webhook_id)
        .order_by(WebhookDeliveryLog.created_at.desc())
    )

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


@router.post("/{webhook_id}/test", status_code=status.HTTP_200_OK, dependencies=[AnalystRequired])
def test_webhook(
    webhook_id: str,
    body: WebhookTestRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
):
    """Send a test ping to this webhook (and only this one), whatever events it subscribes to."""
    hook = db.get(Webhook, webhook_id)
    if not hook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    delivery = send_test_delivery(
        db,
        hook,
        event_type=body.event_type,
        contact_id=body.contact_id,
        data={"test": True, "triggered_by": current_user.email},
    )
    return {
        "status": "sent",
        "delivered_to": 1 if delivery.status == "success" else 0,
        "delivery_id": delivery.id,
        "delivery_status": delivery.status,
    }


@router.post(
    "/{webhook_id}/deliveries/{delivery_id}/retry", status_code=status.HTTP_200_OK, dependencies=[AnalystRequired]
)
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
