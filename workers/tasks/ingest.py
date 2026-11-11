"""
Ingest worker tasks.

Responsibilities:
  - Validate raw events against connector contract
  - Normalize and deduplicate contacts/companies
  - Upsert into core tables
  - Quarantine invalid records
  - Trigger feature recompute on new/updated contacts
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog

from workers.celery_app import app

logger = structlog.get_logger(__name__)

# Idempotency key prefix in Redis
_IDEM_PREFIX = "idem:ingest:"
_IDEM_TTL = 86400  # 24h


def _get_redis():
    import redis as redis_lib

    from app.config import get_settings

    s = get_settings()
    return redis_lib.from_url(s.redis_url, decode_responses=True)


def _get_db():
    from app.database import SessionLocal

    return SessionLocal()


@app.task(
    name="workers.tasks.ingest.process_raw_event",
    bind=True,
    max_retries=5,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def process_raw_event(self, raw_event_id: str):
    """
    Main ingest pipeline for a single raw event.
    Idempotent: safe to retry for the same raw_event_id.
    """
    idem_key = f"{_IDEM_PREFIX}{raw_event_id}"
    r = _get_redis()

    # Idempotency check
    if r.get(idem_key):
        logger.info("ingest_already_processed", raw_event_id=raw_event_id)
        return {"status": "duplicate", "raw_event_id": raw_event_id}

    db = _get_db()
    try:
        from app.models.ingestion import RawEvent

        event = db.get(RawEvent, raw_event_id)
        if not event:
            logger.warning("raw_event_not_found", raw_event_id=raw_event_id)
            return {"status": "not_found"}

        if event.quarantined:
            return {"status": "quarantined"}

        # Validate connector contract
        errors = _validate_event(event)
        if errors:
            event.quarantined = True
            event.quarantine_reason = "; ".join(errors)
            db.commit()
            logger.warning("event_quarantined", raw_event_id=raw_event_id, reasons=errors)
            return {"status": "quarantined", "reasons": errors}

        # Route to correct normalizer
        contact_id = None
        if event.operation == "delete":
            # Contacts are kept: a source deleting its record is not a reason to lose the score history. (It used to re-create the contact.)
            logger.info("ingest_delete_ignored", raw_event_id=raw_event_id, source_system=event.source_system)
        elif event.source_system in ("hubspot", "salesforce", "csv", "seed"):
            contact_id = _upsert_contact(db, event)
        else:
            logger.info("unknown_source_system", source_system=event.source_system)

        # Mark processed
        event.processed = True
        event.processed_at = datetime.now(UTC)
        db.commit()

        # Set idempotency key
        r.setex(idem_key, _IDEM_TTL, "1")

        # Trigger feature recompute if we upserted a contact
        if contact_id:
            recompute_contact_features.delay(contact_id=contact_id)

        return {"status": "ok", "raw_event_id": raw_event_id, "contact_id": contact_id}

    except Exception as exc:
        db.rollback()
        logger.error("ingest_task_failed", raw_event_id=raw_event_id, error=str(exc), exc_info=True)
        raise self.retry(exc=exc) from exc
    finally:
        db.close()


def _validate_event(event) -> list[str]:
    errors = []
    if not event.source_system:
        errors.append("missing source_system")
    if not event.source_record_id:
        errors.append("missing source_record_id")
    if event.operation not in ("insert", "update", "delete"):
        errors.append(f"invalid operation: {event.operation}")
    if not event.raw_payload:
        errors.append("empty raw_payload")
    return errors


def _upsert_contact(db, event) -> str | None:
    """Normalize raw payload and upsert into contacts table. Returns contact_id."""
    from sqlalchemy import select

    from app.models.company import Company
    from app.models.contact import Contact

    payload = event.raw_payload

    # Normalize email
    email = (payload.get("email") or payload.get("properties", {}).get("email", "")).lower().strip()
    if not email or "@" not in email or len(email) > 255:
        return None

    # Find or create company
    company_id = None
    company_name = payload.get("company") or payload.get("properties", {}).get("company", "")
    company_domain = payload.get("domain") or payload.get("properties", {}).get("domain", "")
    if company_domain:
        company = db.scalar(
            select(Company).where(Company.domain == company_domain, Company.source_system == event.source_system)
        )
        if not company:
            company = Company(
                id=str(uuid.uuid4()),
                source_system=event.source_system,
                source_record_id=payload.get("company_id", company_domain),
                name=company_name or company_domain,
                domain=company_domain,
            )
            db.add(company)
            db.flush()
        company_id = company.id

    # Upsert contact
    contact = db.scalar(
        select(Contact).where(
            Contact.source_system == event.source_system,
            Contact.source_record_id == event.source_record_id,
        )
    )

    props = payload.get("properties", payload)
    if contact is None:
        contact = Contact(
            id=str(uuid.uuid4()),
            source_system=event.source_system,
            source_record_id=event.source_record_id,
            email=email,
            first_name=props.get("firstname") or props.get("first_name", ""),
            last_name=props.get("lastname") or props.get("last_name", ""),
            job_title=props.get("jobtitle") or props.get("job_title", ""),
            company_id=company_id,
            lifecycle_stage=props.get("lifecyclestage") or props.get("lifecycle_stage"),
            lead_status=props.get("lead_status"),
            hubspot_contact_id=payload.get("id") if event.source_system == "hubspot" else None,
        )
        db.add(contact)
    else:
        # Update mutable fields only
        if email:
            contact.email = email
        contact.first_name = props.get("firstname") or props.get("first_name") or contact.first_name
        contact.last_name = props.get("lastname") or props.get("last_name") or contact.last_name
        if company_id:
            contact.company_id = company_id
        contact.lifecycle_stage = props.get("lifecyclestage") or props.get("lifecycle_stage") or contact.lifecycle_stage

    db.flush()
    return contact.id


@app.task(
    name="workers.tasks.ingest.recompute_contact_features",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def recompute_contact_features(self, contact_id: str):
    """Lightweight feature refresh triggered after a contact is upserted."""
    from workers.tasks.features import compute_features_for_contact

    compute_features_for_contact(contact_id=contact_id)
