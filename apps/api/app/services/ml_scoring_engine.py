"""
ML Scoring Engine — v2.

Loads a trained XGBoost model from the model registry and scores contacts.
Falls back to v1 deterministic engine if no champion model is available.

Shadow mode: both v1 and v2 run on every contact; only v2 scores are flagged
is_shadow=True so they don't affect CRM sync until promoted.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import structlog

from app.config import get_settings
from app.services.scoring_engine import FeatureVector, ScoreResult, tier_for
from app.services.scoring_engine import score_contact as score_v1

logger = structlog.get_logger(__name__)

# Cache: loaded model dict keyed by artifact_path
_MODEL_CACHE: dict[str, Any] = {}

FEATURE_COLUMNS = [
    "api_calls_7d",
    "api_calls_30d",
    "page_views_7d",
    "pricing_page_visited",
    "email_opens_7d",
    "email_clicks_7d",
    "docs_page_visits_7d",
    "demo_requested",
    "free_trial_active",
    "integration_connected",
    "integrations_count",
    "sessions_7d",
    "days_since_last_activity",
    "company_size_enterprise",  # one-hot
    "company_size_mid_market",
    "company_size_smb",
]


def resolve_artifact(artifact_path: str) -> Path:
    """The model file to load, if it is allowed: an XGBoost JSON file inside the models directory (ML_MODELS_DIR).

    The path comes from a database row, and a pickle file executes code when it is loaded, so neither another folder nor another format is accepted.
    Models trained before this check were saved as pickles (`.pkl`); retrain them (`python -m workers.training.train_model`).
    """
    models_dir = Path(get_settings().ml_models_dir).resolve()
    path = Path(artifact_path).resolve()
    if path.suffix != ".json":
        raise ValueError(
            f"model artifact must be an XGBoost .json file (pickle models are no longer loaded): {artifact_path}"
        )
    if not path.is_relative_to(models_dir):
        raise ValueError(f"model artifact is outside the models directory: {artifact_path}")
    if not path.is_file():
        raise FileNotFoundError(f"Model artifact not found: {artifact_path}")
    return path


def _load_model(artifact_path: str) -> Any:
    """Load (and cache) an XGBoost booster saved with `Booster.save_model(...json)`."""
    if artifact_path in _MODEL_CACHE:
        return _MODEL_CACHE[artifact_path]

    import xgboost as xgb

    booster = xgb.Booster()
    booster.load_model(str(resolve_artifact(artifact_path)))

    _MODEL_CACHE[artifact_path] = booster
    logger.info("ml_model_loaded", path=artifact_path)
    return booster


def _feature_vector_to_row(features: FeatureVector) -> list[float]:
    """Convert a FeatureVector to a flat numeric row matching FEATURE_COLUMNS."""
    size = features.company_size_tier.lower()
    return [
        float(features.api_calls_7d),
        float(features.api_calls_30d),
        float(features.page_views_7d),
        1.0 if features.pricing_page_visited else 0.0,
        float(features.email_opens_7d),
        float(features.email_clicks_7d),
        float(features.docs_page_visits_7d),
        1.0 if features.demo_requested else 0.0,
        1.0 if features.free_trial_active else 0.0,
        1.0 if features.integration_connected else 0.0,
        float(features.integrations_count),
        float(features.sessions_7d),
        float(features.days_since_last_activity),
        1.0 if size == "enterprise" else 0.0,
        1.0 if size == "mid_market" else 0.0,
        1.0 if size == "smb" else 0.0,
    ]


def score_contact_ml(features: FeatureVector, artifact_path: str, model_version: str) -> ScoreResult:
    """
    Score a contact using the loaded XGBoost model.
    Returns a probability [0,1] scaled to [0,100].
    """
    try:
        model = _load_model(artifact_path)
    except (
        Exception
    ) as exc:  # missing, refused, unreadable, or xgboost not installed: the deterministic v1 model still scores
        logger.warning("ml_model_unavailable_fallback_v1", path=artifact_path, error=str(exc))
        return score_v1(features)

    try:
        row = _feature_vector_to_row(features)
        import xgboost as xgb

        prob = float(model.predict(xgb.DMatrix([row], feature_names=FEATURE_COLUMNS))[0])

        lead_score = max(0, min(100, math.floor(prob * 100)))
        tier = tier_for(lead_score)

        # Build feature contributions from model feature importances
        try:
            importances = model.get_score(importance_type="gain")
            contributions = {k: round(importances.get(k, 0) * row[i], 2) for i, k in enumerate(FEATURE_COLUMNS)}
        except Exception:
            contributions = {}

        # Top signals for human-readable reason
        top = sorted(
            [(k, v) for k, v in contributions.items() if v > 0],
            key=lambda x: x[1],
            reverse=True,
        )[:3]
        reason = "ML signals: " + ", ".join(f"{k.replace('_', ' ')} ({v:.1f})" for k, v in top) if top else "ML scored"

        from app.services.scoring_engine import SCORE_CONFIG

        action = SCORE_CONFIG["recommended_actions"].get(tier, "monitor")

        return ScoreResult(
            lead_score=lead_score,
            priority_tier=tier,
            score_reason=reason,
            feature_contributions=contributions,
            model_version=model_version,
            recommended_action=action,
        )

    except Exception as exc:
        logger.error("ml_scoring_error_fallback_v1", error=str(exc))
        return score_v1(features)


def get_champion_model_path() -> tuple[str, str] | None:
    """
    Return (artifact_path, version) for the current champion model.
    Returns None if no champion exists (will fall back to v1).
    """
    try:
        from sqlalchemy import select

        from app.database import SessionLocal
        from app.models.model_registry import ModelRegistry, ModelStage

        db = SessionLocal()
        try:
            row = db.scalar(
                select(ModelRegistry)
                .where(ModelRegistry.stage == ModelStage.CHAMPION)
                .order_by(ModelRegistry.promoted_at.desc())
                .limit(1)
            )
            if row and row.artifact_path:
                return row.artifact_path, row.version
        finally:
            db.close()
    except Exception as exc:
        logger.warning("model_registry_lookup_failed", error=str(exc))
    return None
