"""
Model registry API — manage ML model versions.

Endpoints:
  GET  /models                  — list all registered models
  GET  /models/{id}             — get model details + feature importances
  POST /models/{id}/promote     — promote a model to champion
  POST /models/{id}/shadow      — set a model to shadow stage
  GET  /models/champion/features — feature importance for the current champion
"""
from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import AdminRequired, ViewerRequired
from app.database import get_db
from app.models.model_registry import ModelRegistry, ModelStage
from app.schemas.common import OrmBase

router = APIRouter()
logger = structlog.get_logger(__name__)


class ModelRegistryRead(OrmBase):
    id: str
    version: str
    algorithm: str
    stage: str
    training_rows: int | None
    positive_rate: float | None
    precision_hot: float | None
    recall_hot: float | None
    roc_auc: float | None
    f1_score: float | None
    feature_importances: dict | None
    artifact_path: str | None
    trained_by: str | None
    trained_at: datetime | None
    promoted_at: datetime | None
    created_at: datetime


@router.get("", response_model=list[ModelRegistryRead], dependencies=[ViewerRequired])
def list_models(db: Annotated[Session, Depends(get_db)]):
    return db.scalars(select(ModelRegistry).order_by(ModelRegistry.created_at.desc())).all()


@router.get("/champion/features", dependencies=[ViewerRequired])
def champion_feature_importances(db: Annotated[Session, Depends(get_db)]):
    """Return feature importances for the active champion model."""
    champion = db.scalar(
        select(ModelRegistry)
        .where(ModelRegistry.stage == ModelStage.CHAMPION)
        .order_by(ModelRegistry.promoted_at.desc())
        .limit(1)
    )
    if not champion:
        return {
            "model_version": "1.0.0 (deterministic v1 — no champion ML model)",
            "importances": {},
            "note": "Train and promote a v2 model via: python -m workers.training.train_model --promote",
        }

    importances = champion.feature_importances or {}
    sorted_imp = dict(sorted(importances.items(), key=lambda x: x[1], reverse=True))
    return {
        "model_version": champion.version,
        "stage": champion.stage,
        "roc_auc": champion.roc_auc,
        "importances": sorted_imp,
    }


@router.get("/{model_id}", response_model=ModelRegistryRead, dependencies=[ViewerRequired])
def get_model(model_id: str, db: Annotated[Session, Depends(get_db)]):
    m = db.get(ModelRegistry, model_id)
    if not m:
        raise HTTPException(status_code=404, detail="Model not found")
    return m


@router.post("/{model_id}/promote", dependencies=[AdminRequired])
def promote_model(model_id: str, db: Annotated[Session, Depends(get_db)]):
    """Promote a shadow model to champion. Archives the existing champion."""
    model = db.get(ModelRegistry, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.stage == ModelStage.CHAMPION:
        raise HTTPException(status_code=409, detail="Model is already champion")

    # Archive existing champion
    existing = db.scalar(
        select(ModelRegistry).where(ModelRegistry.stage == ModelStage.CHAMPION)
    )
    if existing:
        existing.stage = ModelStage.ARCHIVED
        existing.archived_at = datetime.now(timezone.utc)

    model.stage = ModelStage.CHAMPION
    model.promoted_at = datetime.now(timezone.utc)
    db.commit()

    logger.info("model_promoted_to_champion", version=model.version)
    return {"status": "promoted", "version": model.version}


@router.post("/{model_id}/shadow", dependencies=[AdminRequired])
def set_shadow(model_id: str, db: Annotated[Session, Depends(get_db)]):
    """Move a training-stage model to shadow (starts scoring alongside v1)."""
    model = db.get(ModelRegistry, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    model.stage = ModelStage.SHADOW
    db.commit()
    return {"status": "shadow", "version": model.version}
