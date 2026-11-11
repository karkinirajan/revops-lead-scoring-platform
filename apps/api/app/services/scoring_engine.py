"""
Deterministic lead scoring engine — v1.

Score is always a function of the same input feature vector + config version.
Changing the config must bump SCORING_MODEL_VERSION in settings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.models.scoring import PriorityTier

settings = get_settings()

# ---------------------------------------------------------------------------
# Versioned scoring configuration — bump version when weights change
# ---------------------------------------------------------------------------

SCORE_CONFIG: dict[str, Any] = {
    "version": "1.0.0",
    # API usage bands: sweet-spot is 5-50 calls/week (per product spec)
    "api_calls_7d_bands": [
        {"min": 0, "max": 0, "score": 0, "label": "no_usage"},
        {"min": 1, "max": 4, "score": 10, "label": "low_usage"},
        {"min": 5, "max": 50, "score": 30, "label": "healthy_usage"},
        {"min": 51, "max": 500, "score": 18, "label": "high_usage"},
        {"min": 501, "max": None, "score": 8, "label": "very_high_possibly_automated"},
    ],
    # Incremental signals with per-unit scores (capped)
    "page_views_7d": {"per_unit": 2, "cap": 14},
    "email_clicks_7d": {"per_unit": 5, "cap": 15},
    "email_opens_7d": {"per_unit": 1, "cap": 5},
    "docs_page_visits_7d": {"per_unit": 1, "cap": 4},
    "sessions_7d": {"per_unit": 1, "cap": 5},
    # Boolean bonuses
    "demo_requested": 20,
    "pricing_page_visited": 10,
    "free_trial_active": 15,
    "integration_connected": 8,
    "integrations_count": {"per_unit": 2, "cap": 10},
    # Recency decay multipliers keyed by days_since_last_activity bucket
    "recency_multipliers": {
        "0_7": 1.0,
        "8_14": 0.90,
        "15_30": 0.70,
        "31_60": 0.45,
        "61_plus": 0.20,
    },
    # Company size multipliers
    "company_size_multipliers": {
        "enterprise": 1.15,
        "mid_market": 1.05,
        "smb": 0.95,
        "unknown": 1.0,
    },
    # Recommended actions by tier
    "recommended_actions": {
        PriorityTier.HOT: "immediate_outreach",
        PriorityTier.WARM: "nurture_sequence",
        PriorityTier.COOL: "re_engagement",
        PriorityTier.COLD: "monitor",
    },
}


# ---------------------------------------------------------------------------
# Input / output types
# ---------------------------------------------------------------------------


@dataclass
class FeatureVector:
    api_calls_7d: int = 0
    api_calls_30d: int = 0
    page_views_7d: int = 0
    pricing_page_visited: bool = False
    email_opens_7d: int = 0
    email_clicks_7d: int = 0
    docs_page_visits_7d: int = 0
    demo_requested: bool = False
    free_trial_active: bool = False
    integration_connected: bool = False
    integrations_count: int = 0
    sessions_7d: int = 0
    days_since_last_activity: int = 999
    company_size_tier: str = "unknown"


@dataclass
class ScoreResult:
    lead_score: int
    priority_tier: str
    score_reason: str
    feature_contributions: dict[str, int] = field(default_factory=dict)
    model_version: str = ""
    recommended_action: str = ""


# ---------------------------------------------------------------------------
# Scoring logic
# ---------------------------------------------------------------------------


def _api_calls_score(api_calls_7d: int) -> tuple[int, str]:
    """Return (score, label) for API call volume using configured bands."""
    for band in SCORE_CONFIG["api_calls_7d_bands"]:
        if (band["max"] is None or api_calls_7d <= band["max"]) and api_calls_7d >= band["min"]:
            return band["score"], band["label"]
    return 0, "unknown"


def _recency_multiplier(days: int) -> float:
    buckets = SCORE_CONFIG["recency_multipliers"]
    if days <= 7:
        return buckets["0_7"]
    if days <= 14:
        return buckets["8_14"]
    if days <= 30:
        return buckets["15_30"]
    if days <= 60:
        return buckets["31_60"]
    return buckets["61_plus"]


def _size_multiplier(size_tier: str) -> float:
    mults = SCORE_CONFIG["company_size_multipliers"]
    return mults.get(size_tier.lower(), mults["unknown"])


def tier_for(score: int) -> str:
    """The tier a score falls in. The boundaries are the SCORING_*_THRESHOLD settings (75, 50 and 25 by default), and the formula and the machine-learning
    model both use this function, so they cannot disagree about them."""
    s = get_settings()
    if score >= s.scoring_hot_threshold:
        return PriorityTier.HOT
    if score >= s.scoring_warm_threshold:
        return PriorityTier.WARM
    if score >= s.scoring_cool_threshold:
        return PriorityTier.COOL
    return PriorityTier.COLD


def score_contact(features: FeatureVector) -> ScoreResult:
    """
    Deterministic scoring function. Same input always yields same output.

    Do NOT add randomness or time-dependent logic inside this function.
    Freshness decay is modelled via days_since_last_activity in the feature vector.
    """
    contributions: dict[str, int] = {}

    # 1. API usage (primary signal)
    api_score, api_label = _api_calls_score(features.api_calls_7d)
    contributions["api_calls_7d"] = api_score

    # 2. Web engagement
    pv_score = min(
        features.page_views_7d * SCORE_CONFIG["page_views_7d"]["per_unit"], SCORE_CONFIG["page_views_7d"]["cap"]
    )
    contributions["page_views_7d"] = pv_score

    docs_score = min(
        features.docs_page_visits_7d * SCORE_CONFIG["docs_page_visits_7d"]["per_unit"],
        SCORE_CONFIG["docs_page_visits_7d"]["cap"],
    )
    contributions["docs_page_visits_7d"] = docs_score

    sessions_score = min(
        features.sessions_7d * SCORE_CONFIG["sessions_7d"]["per_unit"], SCORE_CONFIG["sessions_7d"]["cap"]
    )
    contributions["sessions_7d"] = sessions_score

    # 3. Email engagement
    clicks_score = min(
        features.email_clicks_7d * SCORE_CONFIG["email_clicks_7d"]["per_unit"], SCORE_CONFIG["email_clicks_7d"]["cap"]
    )
    contributions["email_clicks_7d"] = clicks_score

    opens_score = min(
        features.email_opens_7d * SCORE_CONFIG["email_opens_7d"]["per_unit"], SCORE_CONFIG["email_opens_7d"]["cap"]
    )
    contributions["email_opens_7d"] = opens_score

    # 4. Intent signals
    pricing_score = SCORE_CONFIG["pricing_page_visited"] if features.pricing_page_visited else 0
    contributions["pricing_page_visited"] = pricing_score

    demo_score = SCORE_CONFIG["demo_requested"] if features.demo_requested else 0
    contributions["demo_requested"] = demo_score

    trial_score = SCORE_CONFIG["free_trial_active"] if features.free_trial_active else 0
    contributions["free_trial_active"] = trial_score

    integration_score = SCORE_CONFIG["integration_connected"] if features.integration_connected else 0
    contributions["integration_connected"] = integration_score

    int_count_score = min(
        features.integrations_count * SCORE_CONFIG["integrations_count"]["per_unit"],
        SCORE_CONFIG["integrations_count"]["cap"],
    )
    contributions["integrations_count"] = int_count_score

    # 5. Sum raw score
    raw_score = sum(contributions.values())

    # 6. Apply recency decay
    rec_mult = _recency_multiplier(features.days_since_last_activity)
    decayed = raw_score * rec_mult
    contributions["_recency_multiplier"] = int(decayed - raw_score)  # negative penalty

    # 7. Apply company size multiplier
    size_mult = _size_multiplier(features.company_size_tier)
    final_float = decayed * size_mult
    contributions["_company_size_multiplier"] = int(final_float - decayed)

    lead_score = max(0, min(100, math.floor(final_float)))
    tier = tier_for(lead_score)

    # Build human-readable reason
    top_signals = sorted(
        [(k, v) for k, v in contributions.items() if not k.startswith("_") and v > 0],
        key=lambda x: x[1],
        reverse=True,
    )[:3]
    reason_parts = [f"{k.replace('_', ' ')} (+{v})" for k, v in top_signals]
    if rec_mult < 1.0:
        reason_parts.append(f"recency decay ×{rec_mult}")
    reason = "Top signals: " + ", ".join(reason_parts) if reason_parts else "No significant signals"

    return ScoreResult(
        lead_score=lead_score,
        priority_tier=tier,
        score_reason=reason,
        feature_contributions=contributions,
        model_version=SCORE_CONFIG["version"],
        recommended_action=SCORE_CONFIG["recommended_actions"].get(tier, "monitor"),
    )
