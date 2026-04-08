"""
Tests for Feature 1: ML Scoring Engine v2.

Covers:
  - Feature vector → numeric row conversion
  - Tier assignment from score
  - Fallback to v1 when model not found
  - ModelRegistry schema validation
"""
import pytest
from unittest.mock import MagicMock, patch


class TestFeatureVectorToRow:
    def test_row_length_matches_columns(self):
        from app.services.ml_scoring_engine import _feature_vector_to_row, FEATURE_COLUMNS
        from app.services.scoring_engine import FeatureVector

        fv = FeatureVector(
            api_calls_7d=10, api_calls_30d=40, page_views_7d=5,
            pricing_page_visited=True, email_opens_7d=3,
            email_clicks_7d=1, docs_page_visits_7d=2,
            demo_requested=False, free_trial_active=True,
            integration_connected=True, integrations_count=2,
            sessions_7d=3, days_since_last_activity=5,
            company_size_tier="enterprise",
        )
        row = _feature_vector_to_row(fv)
        assert len(row) == len(FEATURE_COLUMNS)

    def test_boolean_features_as_float(self):
        from app.services.ml_scoring_engine import _feature_vector_to_row
        from app.services.scoring_engine import FeatureVector

        fv = FeatureVector(pricing_page_visited=True, demo_requested=False)
        row = _feature_vector_to_row(fv)
        # pricing_page_visited is at index 3
        assert row[3] == 1.0
        # demo_requested is at index 7
        assert row[7] == 0.0

    def test_enterprise_one_hot(self):
        from app.services.ml_scoring_engine import _feature_vector_to_row, FEATURE_COLUMNS
        from app.services.scoring_engine import FeatureVector

        fv = FeatureVector(company_size_tier="enterprise")
        row = _feature_vector_to_row(fv)
        ent_idx = FEATURE_COLUMNS.index("company_size_enterprise")
        mid_idx = FEATURE_COLUMNS.index("company_size_mid_market")
        smb_idx = FEATURE_COLUMNS.index("company_size_smb")
        assert row[ent_idx] == 1.0
        assert row[mid_idx] == 0.0
        assert row[smb_idx] == 0.0

    def test_unknown_size_all_zeros(self):
        from app.services.ml_scoring_engine import _feature_vector_to_row, FEATURE_COLUMNS
        from app.services.scoring_engine import FeatureVector

        fv = FeatureVector(company_size_tier="unknown")
        row = _feature_vector_to_row(fv)
        ent_idx = FEATURE_COLUMNS.index("company_size_enterprise")
        assert row[ent_idx] == 0.0


class TestTierFromScore:
    def test_hot(self):
        from app.services.ml_scoring_engine import _tier_from_score
        assert _tier_from_score(80) == "HOT"

    def test_warm(self):
        from app.services.ml_scoring_engine import _tier_from_score
        assert _tier_from_score(60) == "WARM"

    def test_cool(self):
        from app.services.ml_scoring_engine import _tier_from_score
        assert _tier_from_score(30) == "COOL"

    def test_cold(self):
        from app.services.ml_scoring_engine import _tier_from_score
        assert _tier_from_score(10) == "COLD"

    def test_boundary_hot(self):
        from app.services.ml_scoring_engine import _tier_from_score
        assert _tier_from_score(75) == "HOT"


class TestFallbackToV1:
    def test_file_not_found_falls_back(self):
        from app.services.ml_scoring_engine import score_contact_ml
        from app.services.scoring_engine import FeatureVector

        fv = FeatureVector(api_calls_7d=20, demo_requested=True)
        result = score_contact_ml(fv, "/nonexistent/path/model.pkl", "2.0.0-test")

        # Should fall back to v1 and return a valid ScoreResult
        assert result.lead_score >= 0
        assert result.lead_score <= 100
        assert result.model_version == "1.0.0"  # v1 version, not the requested v2


class TestModelRegistrySchema:
    def test_stage_enum(self):
        from app.models.model_registry import ModelStage
        assert ModelStage.CHAMPION == "champion"
        assert ModelStage.SHADOW == "shadow"
        assert ModelStage.TRAINING == "training"
        assert ModelStage.ARCHIVED == "archived"

    def test_registry_read_schema(self):
        from app.api.v1.model_registry import ModelRegistryRead
        from datetime import datetime, timezone
        r = ModelRegistryRead(
            id="test-id",
            version="2.20260408.1200",
            algorithm="xgboost",
            stage="shadow",
            training_rows=500,
            positive_rate=0.12,
            precision_hot=0.45,
            recall_hot=0.60,
            roc_auc=0.82,
            f1_score=0.51,
            feature_importances={"api_calls_7d": 120.5},
            artifact_path="/data/models/v2.pkl",
            trained_by="scheduler",
            trained_at=datetime.now(timezone.utc),
            promoted_at=None,
            created_at=datetime.now(timezone.utc),
        )
        assert r.roc_auc == 0.82
        assert r.stage == "shadow"
