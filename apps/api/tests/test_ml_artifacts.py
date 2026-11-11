import pickle

import numpy as np
import pytest

xgb = pytest.importorskip("xgboost")

from app.config import get_settings  # noqa: E402
from app.services import ml_scoring_engine as ml  # noqa: E402
from app.services.scoring_engine import FeatureVector, score_contact  # noqa: E402
from tests.conftest import BorrowedSession  # noqa: E402


@pytest.fixture()
def models_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "ml_models_dir", str(tmp_path / "models"))
    (tmp_path / "models").mkdir()
    ml._MODEL_CACHE.clear()
    yield tmp_path / "models"
    ml._MODEL_CACHE.clear()


def train_tiny_model(path):
    """A real booster: demo_requested decides the label."""
    rng = np.random.default_rng(0)
    rows = rng.integers(0, 5, size=(200, len(ml.FEATURE_COLUMNS))).astype(float)
    demo = ml.FEATURE_COLUMNS.index("demo_requested")
    rows[:, demo] = rng.integers(0, 2, size=200)
    labels = rows[:, demo]
    booster = xgb.train(
        {"objective": "binary:logistic", "max_depth": 2, "seed": 0},
        xgb.DMatrix(rows, label=labels, feature_names=ml.FEATURE_COLUMNS),
        num_boost_round=20,
    )
    booster.save_model(str(path))
    return booster


def features(**override):
    base = {
        "api_calls_7d": 0, "api_calls_30d": 0, "page_views_7d": 0, "pricing_page_visited": False, "email_opens_7d": 0, "email_clicks_7d": 0,
        "docs_page_visits_7d": 0, "demo_requested": False, "free_trial_active": False, "integration_connected": False, "integrations_count": 0,
        "sessions_7d": 0, "days_since_last_activity": 30, "company_size_tier": "smb",
    }  # fmt: skip
    base.update(override)
    return FeatureVector(**base)


class TestResolveArtifact:
    def test_a_json_file_in_the_models_directory_is_allowed(self, models_dir):
        path = models_dir / "v2.json"
        path.write_text("{}")
        assert ml.resolve_artifact(str(path)) == path.resolve()

    def test_a_relative_path_is_resolved_from_where_the_process_runs(self, models_dir, monkeypatch):
        (models_dir / "v2.json").write_text("{}")
        monkeypatch.chdir(models_dir.parent)
        assert ml.resolve_artifact("models/v2.json") == (models_dir / "v2.json").resolve()

    @pytest.mark.parametrize("name", ["v1.pkl", "v1.pickle", "v1.joblib", "v1", "v1.json.pkl", "v1.JSON"])
    def test_other_formats_are_refused_without_being_opened(self, models_dir, name):
        (models_dir / name).write_bytes(b"x")
        with pytest.raises(ValueError, match=r"\.json file"):
            ml.resolve_artifact(str(models_dir / name))

    def test_a_file_outside_the_models_directory_is_refused(self, models_dir, tmp_path):
        outside = tmp_path / "elsewhere.json"
        outside.write_text("{}")
        with pytest.raises(ValueError, match="outside the models directory"):
            ml.resolve_artifact(str(outside))

    def test_a_path_that_climbs_out_is_refused(self, models_dir, tmp_path):
        (tmp_path / "secret.json").write_text("{}")
        with pytest.raises(ValueError, match="outside"):
            ml.resolve_artifact(str(models_dir / ".." / "secret.json"))

    def test_a_symlink_pointing_out_is_refused(self, models_dir, tmp_path):
        target = tmp_path / "target.json"
        target.write_text("{}")
        (models_dir / "link.json").symlink_to(target)
        with pytest.raises(ValueError, match="outside"):
            ml.resolve_artifact(str(models_dir / "link.json"))

    def test_a_sibling_directory_with_a_similar_name_is_not_inside(self, models_dir, tmp_path):
        sibling = tmp_path / "models-evil"
        sibling.mkdir()
        (sibling / "v1.json").write_text("{}")
        with pytest.raises(ValueError, match="outside"):
            ml.resolve_artifact(str(sibling / "v1.json"))

    def test_a_missing_file_is_a_file_not_found(self, models_dir):
        with pytest.raises(FileNotFoundError):
            ml.resolve_artifact(str(models_dir / "missing.json"))

    def test_the_directory_itself_is_not_a_model(self, models_dir):
        (models_dir / "dir.json").mkdir()
        with pytest.raises(FileNotFoundError):
            ml.resolve_artifact(str(models_dir / "dir.json"))


class TestScoring:
    def test_a_trained_model_scores_and_explains(self, models_dir):
        train_tiny_model(models_dir / "v2.json")
        wants_demo = ml.score_contact_ml(features(demo_requested=True), str(models_dir / "v2.json"), "2.test")
        no_demo = ml.score_contact_ml(features(demo_requested=False), str(models_dir / "v2.json"), "2.test")
        assert wants_demo.lead_score > 80 > 20 > no_demo.lead_score
        assert (
            wants_demo.model_version == "2.test"
            and wants_demo.priority_tier in {"HOT", "WARM"}
            and no_demo.priority_tier in {"COLD", "COOL"}
        )
        assert (
            wants_demo.score_reason.startswith("ML signals: demo requested")
            and "demo_requested" in wants_demo.feature_contributions
        )

    def test_the_loaded_model_is_cached(self, models_dir):
        train_tiny_model(models_dir / "v2.json")
        ml.score_contact_ml(features(), str(models_dir / "v2.json"), "x")
        first = ml._MODEL_CACHE[str(models_dir / "v2.json")]
        ml.score_contact_ml(features(), str(models_dir / "v2.json"), "x")
        assert ml._MODEL_CACHE[str(models_dir / "v2.json")] is first

    def test_a_pickled_model_is_never_loaded(self, models_dir):
        class Boom:
            def __reduce__(self):
                import os

                return (os.system, ("touch pwned",))

        path = models_dir / "v1.pkl"
        path.write_bytes(pickle.dumps(Boom()))
        result = ml.score_contact_ml(features(demo_requested=True), str(path), "x")
        assert (
            result.model_version == score_contact(features(demo_requested=True)).model_version
        )  # fell back to the deterministic v1 model
        assert not (models_dir.parent / "pwned").exists() and not __import__("pathlib").Path("pwned").exists()

    @pytest.mark.parametrize("make", ["missing", "outside", "garbage"])
    def test_any_problem_with_the_model_falls_back_to_v1(self, models_dir, tmp_path, make, capsys):
        if make == "missing":
            path = models_dir / "none.json"
        elif make == "outside":
            path = tmp_path / "outside.json"
            train_tiny_model(path)
        else:
            path = models_dir / "bad.json"
            path.write_text("this is not a model")
        result = ml.score_contact_ml(features(demo_requested=True), str(path), "x")
        assert result.lead_score == score_contact(features(demo_requested=True)).lead_score
        assert "ml_model_unavailable_fallback_v1" in capsys.readouterr().out

    def test_a_model_that_fails_while_predicting_falls_back_to_v1(self, models_dir, monkeypatch):
        train_tiny_model(models_dir / "v2.json")
        monkeypatch.setattr(
            xgb.Booster, "predict", lambda self, data: (_ for _ in ()).throw(RuntimeError("predict failed"))
        )
        assert (
            ml.score_contact_ml(features(demo_requested=True), str(models_dir / "v2.json"), "x").lead_score
            == score_contact(features(demo_requested=True)).lead_score
        )

    def test_scores_are_clamped_to_0_100(self, models_dir, monkeypatch):
        train_tiny_model(models_dir / "v2.json")
        monkeypatch.setattr(xgb.Booster, "predict", lambda self, data: np.array([1.7]))
        assert ml.score_contact_ml(features(), str(models_dir / "v2.json"), "x").lead_score == 100
        monkeypatch.setattr(xgb.Booster, "predict", lambda self, data: np.array([-0.4]))
        assert ml.score_contact_ml(features(), str(models_dir / "v2.json"), "x").lead_score == 0


class TestChampion:
    def test_the_champion_path_and_version_come_from_the_registry(self, db, monkeypatch):
        from app.models.model_registry import ModelRegistry

        db.add_all(
            [
                ModelRegistry(version="2.0.0", algorithm="xgboost", stage="archived", artifact_path="old.json"),
                ModelRegistry(version="2.1.0", algorithm="xgboost", stage="champion", artifact_path="new.json"),
            ]
        )
        db.commit()
        monkeypatch.setattr("app.database.SessionLocal", lambda: BorrowedSession(db))
        assert ml.get_champion_model_path() == ("new.json", "2.1.0")

    def test_no_champion_means_no_model(self, db, monkeypatch):
        monkeypatch.setattr("app.database.SessionLocal", lambda: BorrowedSession(db))
        assert ml.get_champion_model_path() is None

    def test_a_database_failure_means_no_model(self, monkeypatch):
        def boom():
            raise RuntimeError("database down")

        monkeypatch.setattr("app.database.SessionLocal", boom)
        assert ml.get_champion_model_path() is None


class TestTrainer:
    def test_the_trainer_saves_json_in_the_models_directory(self):
        import inspect

        from workers.training import train_model

        source = inspect.getsource(train_model)
        assert (
            "import pickle" not in source
            and "pickle.dump" not in source
            and ".json" in source
            and "save_model" in source
        )
        assert str(train_model.MODELS_DIR) == get_settings().ml_models_dir
