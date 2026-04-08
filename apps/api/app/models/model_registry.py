"""Model registry — tracks every trained ML model artifact."""
import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ModelStage(StrEnum):
    TRAINING  = "training"
    SHADOW    = "shadow"       # running alongside v1, scores not used in CRM
    CHAMPION  = "champion"     # live model used for production scoring
    ARCHIVED  = "archived"


class ModelRegistry(Base):
    """
    Tracks trained ML model artifacts.

    Each row points to a serialized model file (local path or S3 key).
    Only one model can be CHAMPION at a time.
    """

    __tablename__ = "model_registry"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))

    version: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)  # e.g. "2.0.0", "2.1.3"
    algorithm: Mapped[str] = mapped_column(String(50), nullable=False, default="xgboost")
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default=ModelStage.TRAINING, index=True)

    # Training dataset info
    training_rows: Mapped[int | None] = mapped_column(Integer)
    positive_rate: Mapped[float | None] = mapped_column(Float)   # % converted in training set

    # Evaluation metrics (held-out test set)
    precision_hot: Mapped[float | None] = mapped_column(Float)
    recall_hot: Mapped[float | None] = mapped_column(Float)
    roc_auc: Mapped[float | None] = mapped_column(Float)
    f1_score: Mapped[float | None] = mapped_column(Float)

    # Feature importances (dict: feature_name → importance_score)
    feature_importances: Mapped[dict | None] = mapped_column(JSONB)

    # Artifact storage
    artifact_path: Mapped[str | None] = mapped_column(String(1024))  # local path or s3://bucket/key
    artifact_size_bytes: Mapped[int | None] = mapped_column(Integer)

    # Training provenance
    trained_by: Mapped[str | None] = mapped_column(String(100))   # user_id or "scheduler"
    training_config: Mapped[dict | None] = mapped_column(JSONB)   # hyperparameters used
    notes: Mapped[str | None] = mapped_column(Text)

    trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
