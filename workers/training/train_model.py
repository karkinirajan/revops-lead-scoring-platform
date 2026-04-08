"""
XGBoost model training pipeline for lead scoring v2.

Usage:
    python -m workers.training.train_model --min-rows 500
    python -m workers.training.train_model --shadow   # register as shadow, don't promote
    python -m workers.training.train_model --promote  # register as champion immediately

Training data:
    Pulls all contacts that have a conversion record (positive label = 1)
    and all contacts without one (negative label = 0). Uses the feature
    snapshot from their latest non-shadow lead_score row so the model
    trains on the same features used in production.

Output:
    - Serialized model: data/models/v<version>.pkl
    - Row in model_registry table with metrics and feature importances
"""
from __future__ import annotations

import os
import sys
import uuid
import pickle
import argparse
import math
from datetime import datetime, timezone
from pathlib import Path

# Make API app importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import structlog

logger = structlog.get_logger(__name__)

MODELS_DIR = Path("data/models")
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
    "company_size_enterprise",
    "company_size_mid_market",
    "company_size_smb",
]


def _build_dataset(db) -> tuple[list[list[float]], list[int]]:
    """
    Build (X, y) from the database.
    Positive examples: contacts with a Conversion record.
    Features: pulled from ContactFeature rows.
    """
    from sqlalchemy import select
    from app.models.contact import Contact, ContactFeature
    from app.models.conversion import Conversion
    from app.models.company import Company

    converted_ids = set(
        db.scalars(select(Conversion.contact_id).distinct()).all()
    )

    features_rows = db.execute(
        select(ContactFeature, Contact, Company)
        .join(Contact, ContactFeature.contact_id == Contact.id)
        .outerjoin(Company, Contact.company_id == Company.id)
    ).all()

    X, y = [], []
    for feat, contact, company in features_rows:
        size = (company.size_tier or "unknown").lower() if company else "unknown"
        row = [
            float(feat.api_calls_7d),
            float(feat.api_calls_30d),
            float(feat.page_views_7d),
            1.0 if feat.pricing_page_visited else 0.0,
            float(feat.email_opens_7d),
            float(feat.email_clicks_7d),
            float(feat.docs_page_visits_7d),
            1.0 if feat.demo_requested else 0.0,
            1.0 if feat.free_trial_active else 0.0,
            1.0 if feat.integration_connected else 0.0,
            float(feat.integrations_count),
            float(feat.sessions_7d),
            float(feat.days_since_last_activity),
            1.0 if size == "enterprise" else 0.0,
            1.0 if size == "mid_market" else 0.0,
            1.0 if size == "smb" else 0.0,
        ]
        X.append(row)
        y.append(1 if contact.id in converted_ids else 0)

    return X, y


def train(min_rows: int = 200, shadow: bool = True, promote: bool = False) -> str:
    """
    Train XGBoost model, evaluate, and register in model_registry.
    Returns the new model version string.
    """
    try:
        import xgboost as xgb
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import (
            precision_score, recall_score, roc_auc_score, f1_score as f1
        )
        import numpy as np
    except ImportError as e:
        logger.error("ml_dependencies_missing", error=str(e))
        raise SystemExit(
            "XGBoost/scikit-learn not installed. "
            "Run: pip install xgboost scikit-learn"
        ) from e

    from app.database import SessionLocal
    db = SessionLocal()

    logger.info("training_dataset_build_start")
    X_list, y_list = _build_dataset(db)

    if len(X_list) < min_rows:
        logger.warning(
            "training_insufficient_data",
            rows=len(X_list),
            min_required=min_rows,
        )
        db.close()
        raise ValueError(
            f"Only {len(X_list)} rows available; need at least {min_rows}. "
            "Seed more data or lower --min-rows."
        )

    X = np.array(X_list)
    y = np.array(y_list)
    positive_rate = float(y.mean())
    logger.info("training_dataset_ready", rows=len(X), positive_rate=round(positive_rate, 3))

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y if positive_rate > 0 else None
    )

    # Handle extreme class imbalance
    scale_pos_weight = (len(y_train) - y_train.sum()) / max(y_train.sum(), 1)

    params = {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "max_depth": 4,
        "learning_rate": 0.1,
        "n_estimators": 200,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "scale_pos_weight": scale_pos_weight,
        "random_state": 42,
        "verbosity": 0,
    }

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURE_COLUMNS)
    dtest  = xgb.DMatrix(X_test,  label=y_test,  feature_names=FEATURE_COLUMNS)

    booster = xgb.train(
        {k: v for k, v in params.items() if k not in ("n_estimators",)},
        dtrain,
        num_boost_round=params["n_estimators"],
        evals=[(dtest, "test")],
        verbose_eval=False,
    )

    # Evaluate
    y_prob = booster.predict(dtest)
    y_pred = (y_prob >= 0.5).astype(int)

    metrics = {
        "precision_hot": round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
        "recall_hot":    round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
        "roc_auc":       round(float(roc_auc_score(y_test, y_prob)) if y_test.sum() > 0 else 0.0, 4),
        "f1_score":      round(float(f1(y_test, y_pred, zero_division=0)), 4),
    }
    logger.info("training_metrics", **metrics)

    # Feature importances
    importances = booster.get_score(importance_type="gain")

    # Persist artifact
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    version = f"2.{datetime.now(timezone.utc).strftime('%Y%m%d.%H%M')}"
    artifact_path = str(MODELS_DIR / f"v{version}.pkl")
    with open(artifact_path, "wb") as f:
        pickle.dump(booster, f)
    artifact_size = os.path.getsize(artifact_path)
    logger.info("model_artifact_saved", path=artifact_path, size_bytes=artifact_size)

    # Register in DB
    from app.models.model_registry import ModelRegistry, ModelStage
    stage = ModelStage.CHAMPION if promote else ModelStage.SHADOW if shadow else ModelStage.TRAINING

    # If promoting, archive existing champion
    if promote:
        from sqlalchemy import select
        existing_champion = db.scalar(
            select(ModelRegistry).where(ModelRegistry.stage == ModelStage.CHAMPION)
        )
        if existing_champion:
            existing_champion.stage = ModelStage.ARCHIVED
            existing_champion.archived_at = datetime.now(timezone.utc)

    entry = ModelRegistry(
        version=version,
        algorithm="xgboost",
        stage=stage,
        training_rows=len(X),
        positive_rate=positive_rate,
        precision_hot=metrics["precision_hot"],
        recall_hot=metrics["recall_hot"],
        roc_auc=metrics["roc_auc"],
        f1_score=metrics["f1_score"],
        feature_importances=importances,
        artifact_path=artifact_path,
        artifact_size_bytes=artifact_size,
        training_config=params,
        trained_by="cli",
        trained_at=datetime.now(timezone.utc),
        promoted_at=datetime.now(timezone.utc) if promote else None,
    )
    db.add(entry)
    db.commit()
    db.close()

    logger.info("model_registered", version=version, stage=stage)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train XGBoost lead scoring model v2")
    parser.add_argument("--min-rows", type=int, default=200, help="Minimum training rows required")
    parser.add_argument("--shadow", action="store_true", default=True, help="Register as shadow (default)")
    parser.add_argument("--promote", action="store_true", default=False, help="Register as champion immediately")
    args = parser.parse_args()

    version = train(min_rows=args.min_rows, shadow=not args.promote, promote=args.promote)
    print(f"Model trained and registered: version={version}")
