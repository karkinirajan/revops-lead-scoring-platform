"""Turning a contact's stored signals into a stored score: the parts the scoring task and the command line share, so the two cannot drift apart."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.scoring import LeadScore
from app.services.scoring_engine import FeatureVector, ScoreResult

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.contact import Contact

NO_ACTIVITY_DAYS = 999  # a contact with no signals at all counts as long inactive


def feature_vector(contact: Contact) -> FeatureVector:
    """The engine's input for a contact: its feature row (a contact that has none is scored as having no signals) and its company's size, which the formula
    weighs and the machine-learning model was trained on."""
    f = contact.features
    size = (contact.company.size_tier or "unknown").lower() if contact.company else "unknown"
    return FeatureVector(
        api_calls_7d=f.api_calls_7d if f else 0,
        api_calls_30d=f.api_calls_30d if f else 0,
        page_views_7d=f.page_views_7d if f else 0,
        pricing_page_visited=f.pricing_page_visited if f else False,
        email_opens_7d=f.email_opens_7d if f else 0,
        email_clicks_7d=f.email_clicks_7d if f else 0,
        docs_page_visits_7d=f.docs_page_visits_7d if f else 0,
        demo_requested=f.demo_requested if f else False,
        free_trial_active=f.free_trial_active if f else False,
        integration_connected=f.integration_connected if f else False,
        integrations_count=f.integrations_count if f else 0,
        sessions_7d=f.sessions_7d if f else 0,
        days_since_last_activity=f.days_since_last_activity if f else NO_ACTIVITY_DAYS,
        company_size_tier=size,
    )


def latest_live_score(db: Session, contact_id: str) -> LeadScore | None:
    """The contact's most recent live score: the one a new live score is compared with. A shadow score is never what anyone has been told."""
    return db.scalar(
        select(LeadScore)
        .where(LeadScore.contact_id == contact_id, LeadScore.is_shadow.is_(False))
        .order_by(LeadScore.scored_at.desc())
        .limit(1)
    )


def new_score(
    contact: Contact, fv: FeatureVector, result: ScoreResult, *, run_id: str | None, is_shadow: bool
) -> LeadScore:
    """The row that records `result` for `contact`. It keeps the few signals the next score is compared with (see `webhook_service.notify_score_change`)."""
    f = contact.features
    return LeadScore(
        id=str(uuid.uuid4()),
        contact_id=contact.id,
        company_id=contact.company_id,
        scoring_run_id=run_id,
        lead_score=result.lead_score,
        priority_tier=result.priority_tier,
        model_version=result.model_version,
        score_reason=result.score_reason,
        feature_contributions=result.feature_contributions,
        feature_snapshot={
            "api_calls_7d": fv.api_calls_7d,
            "page_views_7d": fv.page_views_7d,
            "demo_requested": fv.demo_requested,
            "days_since_last_activity": fv.days_since_last_activity,
        },
        recommended_action=result.recommended_action,
        is_shadow=is_shadow,
        scored_at=datetime.now(UTC),
        feature_freshness_at=f.computed_at if f else None,
    )
