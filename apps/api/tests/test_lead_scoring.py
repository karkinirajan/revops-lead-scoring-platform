"""The pieces the scoring task and the command line share."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.scoring import LeadScore
from app.services.lead_scoring import NO_ACTIVITY_DAYS, feature_vector, latest_live_score, new_score
from app.services.scoring_engine import FeatureVector, score_contact

# every field a different number, so that two being swapped cannot go unnoticed
FEATURES = SimpleNamespace(
    api_calls_7d=1,
    api_calls_30d=2,
    page_views_7d=3,
    pricing_page_visited=True,
    email_opens_7d=4,
    email_clicks_7d=5,
    docs_page_visits_7d=6,
    demo_requested=True,
    free_trial_active=True,
    integration_connected=True,
    integrations_count=7,
    sessions_7d=8,
    days_since_last_activity=9,
    computed_at=datetime(2026, 11, 10, 12, 0, tzinfo=UTC),
)


def contact_like(features=FEATURES, size="smb"):
    return SimpleNamespace(features=features, company=SimpleNamespace(size_tier=size) if size is not False else None)


class TestFeatureVector:
    def test_every_signal_is_carried_over(self):
        fv = feature_vector(contact_like())
        assert asdict(fv) == {
            "api_calls_7d": 1,
            "api_calls_30d": 2,
            "page_views_7d": 3,
            "pricing_page_visited": True,
            "email_opens_7d": 4,
            "email_clicks_7d": 5,
            "docs_page_visits_7d": 6,
            "demo_requested": True,
            "free_trial_active": True,
            "integration_connected": True,
            "integrations_count": 7,
            "sessions_7d": 8,
            "days_since_last_activity": 9,
            "company_size_tier": "smb",
        }

    @pytest.mark.parametrize(
        ("size", "expected"),
        [
            ("enterprise", "enterprise"),
            ("Mid_Market", "mid_market"),
            (None, "unknown"),
            ("", "unknown"),
            (False, "unknown"),
        ],
    )
    def test_the_company_size_comes_from_the_company(self, size, expected):
        assert feature_vector(contact_like(size=size)).company_size_tier == expected

    def test_the_formula_weighs_the_size_the_vector_carries(self):
        enterprise = score_contact(feature_vector(contact_like(size="enterprise"))).lead_score
        smb = score_contact(feature_vector(contact_like(size="smb"))).lead_score
        assert enterprise > smb

    def test_a_contact_with_no_features_has_no_signals_and_has_been_inactive_a_long_time(self):
        fv = feature_vector(contact_like(features=None, size=False))
        assert fv == FeatureVector(days_since_last_activity=NO_ACTIVITY_DAYS)
        assert NO_ACTIVITY_DAYS == 999
        assert score_contact(fv).priority_tier == "COLD"


class TestLatestLiveScore:
    def add(self, db, contact, score, tier, *, shadow=False, minutes_ago=0):
        row = LeadScore(
            contact_id=contact.id,
            lead_score=score,
            priority_tier=tier,
            model_version="1.0.0",
            is_shadow=shadow,
            scored_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        )
        db.add(row)
        db.commit()
        return row

    def test_a_contact_never_scored_has_none(self, db, make_contact):
        assert latest_live_score(db, make_contact().id) is None

    def test_it_is_the_most_recent_live_score(self, db, make_contact):
        contact = make_contact()
        self.add(db, contact, 10, "COLD", minutes_ago=30)
        newest = self.add(db, contact, 60, "WARM", minutes_ago=5)
        self.add(db, contact, 30, "COOL", minutes_ago=20)
        assert latest_live_score(db, contact.id).id == newest.id

    def test_a_newer_shadow_score_does_not_count(self, db, make_contact):
        contact = make_contact()
        live = self.add(db, contact, 60, "WARM", minutes_ago=30)
        self.add(db, contact, 95, "HOT", shadow=True, minutes_ago=1)
        assert latest_live_score(db, contact.id).id == live.id

    def test_another_contacts_scores_do_not_count(self, db, make_contact):
        mine, other = make_contact(), make_contact()
        self.add(db, other, 90, "HOT")
        assert latest_live_score(db, mine.id) is None


class TestNewScore:
    def test_it_records_the_result_the_signals_and_where_it_came_from(self, db, make_contact):
        contact = make_contact(
            company={"name": "Acme"},
            features={"api_calls_7d": 20, "demo_requested": True, "days_since_last_activity": 2},
        )
        fv = feature_vector(contact)
        result = score_contact(fv)
        row = new_score(contact, fv, result, run_id="11111111-1111-4111-8111-111111111111", is_shadow=True)
        assert row.contact_id == contact.id and row.company_id == contact.company_id and row.company_id is not None
        assert row.scoring_run_id == "11111111-1111-4111-8111-111111111111" and row.is_shadow is True
        assert (row.lead_score, row.priority_tier, row.model_version) == (
            result.lead_score,
            result.priority_tier,
            result.model_version,
        )
        assert row.score_reason == result.score_reason and row.recommended_action == result.recommended_action
        assert row.feature_contributions == result.feature_contributions
        assert row.feature_snapshot == {
            "api_calls_7d": 20,
            "page_views_7d": 0,
            "demo_requested": True,
            "days_since_last_activity": 2,
        }
        assert row.feature_freshness_at == contact.features.computed_at
        assert abs((row.scored_at - datetime.now(UTC)).total_seconds()) < 5 and row.id

    def test_a_live_score_without_a_run_and_a_contact_without_features(self, make_contact):
        contact = make_contact()
        fv = feature_vector(contact)
        row = new_score(contact, fv, score_contact(fv), run_id=None, is_shadow=False)
        assert row.scoring_run_id is None and row.is_shadow is False and row.feature_freshness_at is None
        assert row.feature_snapshot["days_since_last_activity"] == NO_ACTIVITY_DAYS

    def test_each_row_has_its_own_id(self, make_contact):
        contact = make_contact()
        fv = feature_vector(contact)
        a = new_score(contact, fv, score_contact(fv), run_id=None, is_shadow=False)
        b = new_score(contact, fv, score_contact(fv), run_id=None, is_shadow=False)
        assert a.id != b.id


class TestSizeReachesTheStoredScore:
    def test_the_task_scores_an_enterprise_contact_higher_than_an_identical_smb_one(self, worker_db, make_contact):
        from workers.tasks import scoring as scoring_tasks

        features = {"api_calls_7d": 20, "page_views_7d": 5, "demo_requested": True, "days_since_last_activity": 2}
        enterprise = make_contact(company={"name": "Big Co", "size_tier": "enterprise"}, features=features)
        small = make_contact(company={"name": "Small Co", "size_tier": "smb"}, features=features)
        big_score = scoring_tasks.score_single_contact(enterprise.id)["score"]
        small_score = scoring_tasks.score_single_contact(small.id)["score"]
        assert big_score > small_score
