"""Determinism and correctness tests for the scoring engine.

These are pure unit tests — no DB, no network.
"""

import pytest

from app.config import get_settings
from app.services.scoring_engine import FeatureVector, PriorityTier, score_contact, tier_for


def make_features(**kwargs) -> FeatureVector:
    return FeatureVector(**kwargs)


class TestDeterminism:
    def test_same_input_same_output(self):
        fv = make_features(api_calls_7d=20, page_views_7d=10, email_clicks_7d=2, days_since_last_activity=5)
        r1 = score_contact(fv)
        r2 = score_contact(fv)
        assert r1.lead_score == r2.lead_score
        assert r1.priority_tier == r2.priority_tier
        assert r1.feature_contributions == r2.feature_contributions

    def test_different_inputs_different_outputs(self):
        hot = make_features(api_calls_7d=20, demo_requested=True, pricing_page_visited=True, days_since_last_activity=2)
        cold = make_features()
        assert score_contact(hot).lead_score > score_contact(cold).lead_score


class TestAPICallBands:
    def test_no_usage_zero_score(self):
        result = score_contact(make_features(api_calls_7d=0))
        assert result.feature_contributions["api_calls_7d"] == 0

    def test_low_usage_10_points(self):
        result = score_contact(make_features(api_calls_7d=3))
        assert result.feature_contributions["api_calls_7d"] == 10

    def test_sweet_spot_30_points(self):
        for n in [5, 25, 50]:
            result = score_contact(make_features(api_calls_7d=n))
            assert result.feature_contributions["api_calls_7d"] == 30, f"Failed for api_calls_7d={n}"

    def test_high_usage_18_points(self):
        result = score_contact(make_features(api_calls_7d=100))
        assert result.feature_contributions["api_calls_7d"] == 18

    def test_very_high_usage_8_points(self):
        result = score_contact(make_features(api_calls_7d=1000))
        assert result.feature_contributions["api_calls_7d"] == 8


class TestIntentSignals:
    def test_demo_requested_bonus(self):
        with_demo = score_contact(make_features(demo_requested=True))
        without_demo = score_contact(make_features(demo_requested=False))
        assert with_demo.lead_score > without_demo.lead_score

    def test_pricing_page_bonus(self):
        with_pricing = score_contact(make_features(pricing_page_visited=True))
        without = score_contact(make_features())
        assert with_pricing.lead_score > without.lead_score


class TestRecencyDecay:
    def test_recent_activity_no_decay(self):
        fv = make_features(api_calls_7d=20, days_since_last_activity=3)
        assert score_contact(fv).feature_contributions["_recency_multiplier"] == 0

    def test_stale_activity_penalized(self):
        fresh = score_contact(make_features(api_calls_7d=20, days_since_last_activity=3))
        stale = score_contact(make_features(api_calls_7d=20, days_since_last_activity=45))
        assert fresh.lead_score > stale.lead_score


class TestPriorityTiers:
    def test_hot_tier(self):
        result = score_contact(
            make_features(
                api_calls_7d=20,
                demo_requested=True,
                pricing_page_visited=True,
                email_clicks_7d=3,
                free_trial_active=True,
                days_since_last_activity=2,
            )
        )
        assert result.priority_tier == PriorityTier.HOT

    def test_cold_tier_no_signals(self):
        result = score_contact(make_features())
        assert result.priority_tier == PriorityTier.COLD

    def test_score_bounded_0_100(self):
        # Max out every signal
        extreme = make_features(
            api_calls_7d=25,
            page_views_7d=100,
            email_clicks_7d=100,
            email_opens_7d=100,
            demo_requested=True,
            pricing_page_visited=True,
            free_trial_active=True,
            integration_connected=True,
            integrations_count=10,
            sessions_7d=100,
            days_since_last_activity=1,
        )
        result = score_contact(extreme)
        assert 0 <= result.lead_score <= 100


class TestExplainability:
    def test_feature_contributions_present(self):
        result = score_contact(make_features(api_calls_7d=10, page_views_7d=5))
        assert "api_calls_7d" in result.feature_contributions
        assert "page_views_7d" in result.feature_contributions

    def test_score_reason_is_nonempty_string(self):
        result = score_contact(make_features(api_calls_7d=10))
        assert isinstance(result.score_reason, str)
        assert len(result.score_reason) > 0

    def test_model_version_present(self):
        result = score_contact(make_features())
        assert result.model_version == "1.0.0"


class TestTierFor:
    @pytest.mark.parametrize(
        ("score", "tier"),
        [(100, "HOT"), (75, "HOT"), (74, "WARM"), (50, "WARM"), (49, "COOL"), (25, "COOL"), (24, "COLD"), (0, "COLD")],
    )
    def test_the_default_boundaries(self, score, tier):
        assert tier_for(score) == tier

    def test_the_boundaries_are_the_settings(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "scoring_hot_threshold", 90)
        monkeypatch.setattr(settings, "scoring_warm_threshold", 60)
        monkeypatch.setattr(settings, "scoring_cool_threshold", 30)
        assert [tier_for(n) for n in (95, 90, 89, 60, 59, 30, 29)] == [
            "HOT",
            "HOT",
            "WARM",
            "WARM",
            "COOL",
            "COOL",
            "COLD",
        ]

    def test_the_formula_uses_them_too(self, monkeypatch):
        features = FeatureVector(
            api_calls_7d=20, demo_requested=True, free_trial_active=True, days_since_last_activity=1
        )
        score = score_contact(features).lead_score
        assert score_contact(features).priority_tier == tier_for(score)
        monkeypatch.setattr(get_settings(), "scoring_hot_threshold", score + 1)
        monkeypatch.setattr(get_settings(), "scoring_warm_threshold", score)
        assert score_contact(features).priority_tier == "WARM"  # the same score, now one below the hot boundary
