"""The data routes: contacts, companies, scoring, analytics and the model registry."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.conversion import Conversion
from app.models.model_registry import ModelRegistry
from app.models.scoring import LeadScore, ScoringRun
from workers.tasks import scoring as scoring_tasks

MISSING = "00000000-0000-0000-0000-000000000000"


class TestContacts:
    def body(self, **override):
        return {"source_system": "hubspot", "source_record_id": "h-1", "email": "ada@example.com", **override}

    def test_crud(self, client, auth):
        analyst = auth("analyst")
        created = client.post(
            "/api/v1/contacts", headers=analyst, json=self.body(first_name="Ada", last_name="Lovelace")
        )
        assert created.status_code == 201
        cid = created.json()["id"]
        assert client.get(f"/api/v1/contacts/{cid}", headers=analyst).json()["first_name"] == "Ada"
        patched = client.patch(f"/api/v1/contacts/{cid}", headers=analyst, json={"job_title": "Engineer"})
        assert (
            patched.status_code == 200
            and patched.json()["job_title"] == "Engineer"
            and patched.json()["first_name"] == "Ada"
        )
        assert client.delete(f"/api/v1/contacts/{cid}", headers=analyst).status_code == 204
        assert client.get(f"/api/v1/contacts/{cid}", headers=analyst).status_code == 404

    def test_roles(self, client, auth, make_contact):
        contact = make_contact()
        viewer = auth("viewer")
        assert client.get("/api/v1/contacts", headers=viewer).status_code == 200
        assert client.post("/api/v1/contacts", headers=viewer, json=self.body()).status_code == 403
        assert client.patch(f"/api/v1/contacts/{contact.id}", headers=viewer, json={}).status_code == 403
        assert client.delete(f"/api/v1/contacts/{contact.id}", headers=viewer).status_code == 403
        assert client.get("/api/v1/contacts").status_code == 401

    def test_an_invalid_email_is_a_422(self, client, auth):
        assert client.post("/api/v1/contacts", headers=auth("analyst"), json=self.body(email="nope")).status_code == 422

    def test_unknown_contacts_are_a_404(self, client, auth):
        analyst = auth("analyst")
        assert client.get(f"/api/v1/contacts/{MISSING}", headers=analyst).status_code == 404
        assert client.patch(f"/api/v1/contacts/{MISSING}", headers=analyst, json={}).status_code == 404
        assert client.delete(f"/api/v1/contacts/{MISSING}", headers=analyst).status_code == 404

    def test_listing_pages_and_filters(self, client, auth, make_contact):
        for i in range(5):
            make_contact(
                email=f"p{i}@example.com",
                lifecycle_stage="lead" if i < 3 else "customer",
                source_system="hubspot" if i % 2 else "csv",
            )
        viewer = auth("viewer")
        page = client.get("/api/v1/contacts?page_size=2&page=2", headers=viewer).json()
        assert page["total"] == 5 and len(page["items"]) == 2 and page["pages"] == 3 and page["page"] == 2
        assert client.get("/api/v1/contacts?lifecycle_stage=customer", headers=viewer).json()["total"] == 2
        assert client.get("/api/v1/contacts?source_system=csv", headers=viewer).json()["total"] == 3
        assert client.get("/api/v1/contacts?page_size=501", headers=viewer).status_code == 422
        assert client.get("/api/v1/contacts?page=0", headers=viewer).status_code == 422

    def test_search_matches_email_and_names_ignoring_case(self, client, auth, make_contact):
        make_contact(email="grace@navy.test", first_name="Grace", last_name="Hopper")
        make_contact(email="alan@bletchley.test", first_name="Alan", last_name="Turing")
        viewer = auth("viewer")
        assert client.get("/api/v1/contacts?search=HOPPER", headers=viewer).json()["total"] == 1
        assert client.get("/api/v1/contacts?search=bletchley", headers=viewer).json()["total"] == 1
        assert client.get("/api/v1/contacts?search=nobody", headers=viewer).json()["total"] == 0

    @pytest.mark.parametrize("term", ["%", "_", "%%", "a%", "\\", "%_%"])
    def test_wildcards_in_the_search_are_taken_literally(self, client, auth, make_contact, term):
        make_contact(email="plain@example.com", first_name="Plain")
        make_contact(email="under_score@example.com", first_name="Under_score")
        make_contact(email="percent%sign@example.com", first_name="Percent%sign")
        viewer = auth("viewer")
        total = client.get("/api/v1/contacts", params={"search": term}, headers=viewer).json()["total"]
        assert total == {"%": 1, "_": 1, "%%": 0, "a%": 0, "\\": 0, "%_%": 0}[term]

    def test_a_huge_search_is_a_422(self, client, auth):
        assert client.get("/api/v1/contacts", params={"search": "x" * 201}, headers=auth("viewer")).status_code == 422


class TestCompanies:
    def body(self, **override):
        return {
            "source_system": "hubspot",
            "source_record_id": "c-1",
            "name": "Acme",
            "domain": "acme.test",
            **override,
        }

    def test_crud_and_roles(self, client, auth):
        analyst = auth("analyst")
        created = client.post(
            "/api/v1/companies", headers=analyst, json=self.body(industry="Fintech", size_tier="enterprise")
        )
        assert created.status_code == 201
        cid = created.json()["id"]
        assert (
            client.patch(f"/api/v1/companies/{cid}", headers=analyst, json={"industry": "Banking"}).json()["industry"]
            == "Banking"
        )
        assert client.get(f"/api/v1/companies/{cid}", headers=auth("viewer")).json()["name"] == "Acme"
        assert client.post("/api/v1/companies", headers=auth("viewer"), json=self.body()).status_code == 403
        assert client.get(f"/api/v1/companies/{MISSING}", headers=analyst).status_code == 404
        assert client.patch(f"/api/v1/companies/{MISSING}", headers=analyst, json={}).status_code == 404

    def test_filters_and_literal_wildcard_search(self, client, auth, make_contact):
        make_contact(
            company={"name": "Acme Corp", "domain": "acme.test", "industry": "Fintech", "size_tier": "enterprise"}
        )
        make_contact(company={"name": "50%_Off Ltd", "domain": "off.test", "industry": "Retail", "size_tier": "smb"})
        viewer = auth("viewer")
        assert client.get("/api/v1/companies?size_tier=smb", headers=viewer).json()["total"] == 1
        assert client.get("/api/v1/companies?industry=Fintech", headers=viewer).json()["total"] == 1
        assert client.get("/api/v1/companies?search=ACME", headers=viewer).json()["total"] == 1
        assert (
            client.get("/api/v1/companies", params={"search": "%"}, headers=viewer).json()["total"] == 1
        )  # only the one with a literal %
        assert client.get("/api/v1/companies", params={"search": "off.test"}, headers=viewer).json()["total"] == 1


class TestScoringLeads:
    def test_leads_are_ranked_by_their_latest_score_and_shadow_scores_are_ignored(self, client, auth, make_contact, db):
        low = make_contact(email="low@example.com", score=30, tier="COOL")
        high = make_contact(email="high@example.com", score=90, tier="HOT")
        mid = make_contact(email="mid@example.com", score=60, tier="WARM")
        db.add(
            LeadScore(contact_id=high.id, lead_score=99, priority_tier="HOT", model_version="2.0", is_shadow=True)
        )  # a shadow model's opinion
        old = db.query(LeadScore).filter_by(contact_id=mid.id).one()
        db.add(
            LeadScore(
                contact_id=mid.id,
                lead_score=95,
                priority_tier="HOT",
                model_version="1.0.0",
                scored_at=old.scored_at + timedelta(hours=1),
            )
        )  # newer
        db.commit()
        body = client.get("/api/v1/scoring/leads", headers=auth("viewer")).json()
        assert [(i["email"], i["lead_score"]) for i in body["items"]] == [
            ("mid@example.com", 95),
            ("high@example.com", 90),
            ("low@example.com", 30),
        ]
        assert body["total"] == 3 and low and high

    def test_filters_and_paging(self, client, auth, make_contact):
        for i, (score, tier) in enumerate([(90, "HOT"), (80, "HOT"), (60, "WARM"), (30, "COOL")]):
            make_contact(email=f"f{i}@example.com", score=score, tier=tier)
        viewer = auth("viewer")
        assert client.get("/api/v1/scoring/leads?priority_tier=hot", headers=viewer).json()["total"] == 2
        assert client.get("/api/v1/scoring/leads?min_score=61", headers=viewer).json()["total"] == 2
        assert client.get("/api/v1/scoring/leads?model_version=9.9", headers=viewer).json()["total"] == 0
        page = client.get("/api/v1/scoring/leads?page_size=3&page=2", headers=viewer).json()
        assert len(page["items"]) == 1 and page["pages"] == 2
        assert client.get("/api/v1/scoring/leads?min_score=101", headers=viewer).status_code == 422

    def test_company_filter(self, client, auth, make_contact):
        a = make_contact(email="a@example.com", score=70, tier="WARM", company={"name": "A"})
        make_contact(email="b@example.com", score=70, tier="WARM", company={"name": "B"})
        body = client.get(f"/api/v1/scoring/leads?company_id={a.company_id}", headers=auth("viewer")).json()
        assert [i["email"] for i in body["items"]] == ["a@example.com"] and body["items"][0]["company_name"] == "A"

    def test_it_needs_a_login(self, client):
        assert client.get("/api/v1/scoring/leads").status_code == 401


class TestSimulate:
    FEATURES = {
        "api_calls_7d": 100,
        "pricing_page_visited": True,
        "demo_requested": True,
        "free_trial_active": True,
        "integration_connected": True,
        "days_since_last_activity": 1,
    }

    def test_a_strong_lead_scores_higher_than_an_idle_one(self, client, auth):
        viewer = auth("viewer")
        strong = client.post("/api/v1/scoring/simulate", headers=viewer, json=self.FEATURES).json()
        idle = client.post("/api/v1/scoring/simulate", headers=viewer, json={}).json()
        assert (
            strong["lead_score"] > idle["lead_score"]
            and strong["priority_tier"] in {"HOT", "WARM"}
            and idle["priority_tier"] == "COLD"
        )
        assert 0 <= idle["lead_score"] <= strong["lead_score"] <= 100 and strong["feature_contributions"]

    def test_it_needs_a_login(self, client):
        assert client.post("/api/v1/scoring/simulate", json={}).status_code == 401

    def test_nothing_is_stored(self, client, auth, db):
        client.post("/api/v1/scoring/simulate", headers=auth("viewer"), json=self.FEATURES)
        assert db.query(LeadScore).count() == 0


class TestScoringRuns:
    def test_a_run_is_recorded_and_queued(self, client, auth, monkeypatch):
        queued = []
        monkeypatch.setattr(scoring_tasks.run_scoring_batch, "delay", lambda **kwargs: queued.append(kwargs))
        resp = client.post(
            "/api/v1/scoring/runs", headers=auth("analyst"), json={"filter_segment": "enterprise", "is_shadow": True}
        )
        assert resp.status_code == 202
        run = resp.json()
        assert (run["status"], run["filter_segment"], run["is_shadow"], run["triggered_by"]) == (
            "pending",
            "enterprise",
            True,
            "api",
        )
        assert queued == [{"run_id": run["id"], "filter_segment": "enterprise", "is_shadow": True}]

    def test_a_queue_that_is_down_still_records_the_run(self, client, auth, monkeypatch, db):
        monkeypatch.setattr(
            scoring_tasks.run_scoring_batch, "delay", lambda **kwargs: (_ for _ in ()).throw(ConnectionError("down"))
        )
        assert client.post("/api/v1/scoring/runs", headers=auth("analyst"), json={}).status_code == 202
        assert db.query(ScoringRun).count() == 1

    def test_viewers_cannot_trigger_runs_but_can_read_them(self, client, auth, monkeypatch):
        monkeypatch.setattr(scoring_tasks.run_scoring_batch, "delay", lambda **kwargs: None)
        assert client.post("/api/v1/scoring/runs", headers=auth("viewer"), json={}).status_code == 403
        run = client.post("/api/v1/scoring/runs", headers=auth("analyst"), json={}).json()
        viewer = auth("viewer")
        assert client.get(f"/api/v1/scoring/runs/{run['id']}", headers=viewer).json()["id"] == run["id"]
        assert [r["id"] for r in client.get("/api/v1/scoring/runs", headers=viewer).json()] == [run["id"]]
        assert client.get(f"/api/v1/scoring/runs/{MISSING}", headers=viewer).status_code == 404
        assert client.get("/api/v1/scoring/runs?limit=101", headers=viewer).status_code == 422


class TestConversionsAndAnalytics:
    def converted(self, db, contact, *, value=1000.0, days=10, when=None):
        score = db.query(LeadScore).filter_by(contact_id=contact.id).first()
        db.add(
            Conversion(
                contact_id=contact.id,
                converted_at=when or datetime.now(UTC),
                deal_value=value,
                days_to_close=days,
                source="manual",
                score_at_conversion=score.lead_score,
                tier_at_conversion=score.priority_tier,
                model_version_at_conversion=score.model_version,
            )
        )
        db.commit()

    def test_a_manual_conversion_captures_the_score_at_the_time(self, client, auth, make_contact):
        contact = make_contact(score=77, tier="WARM")
        resp = client.post(
            "/api/v1/analytics/conversions",
            headers=auth("analyst"),
            json={"contact_id": contact.id, "converted_at": "2026-02-01T00:00:00Z", "deal_value": 5000},
        )
        assert resp.status_code == 201
        assert (resp.json()["score_at_conversion"], resp.json()["tier_at_conversion"], resp.json()["deal_value"]) == (
            77,
            "WARM",
            5000.0,
        )

    def test_a_conversion_for_an_unknown_contact_is_a_404(self, client, auth):
        assert (
            client.post(
                "/api/v1/analytics/conversions",
                headers=auth("analyst"),
                json={"contact_id": MISSING, "converted_at": "2026-02-01T00:00:00Z"},
            ).status_code
            == 404
        )

    def test_viewers_cannot_record_conversions(self, client, auth, make_contact):
        contact = make_contact(score=77, tier="WARM")
        assert (
            client.post(
                "/api/v1/analytics/conversions",
                headers=auth("viewer"),
                json={"contact_id": contact.id, "converted_at": "2026-02-01T00:00:00Z"},
            ).status_code
            == 403
        )

    def test_listing_filters_by_tier(self, client, auth, make_contact, db):
        self.converted(db, make_contact(score=90, tier="HOT"))
        self.converted(db, make_contact(score=40, tier="COOL"))
        viewer = auth("viewer")
        assert client.get("/api/v1/analytics/conversions", headers=viewer).json()["total"] == 2
        hot = client.get("/api/v1/analytics/conversions?tier=hot", headers=viewer).json()
        assert hot["total"] == 1 and hot["items"][0]["tier_at_conversion"] == "HOT"

    def test_model_accuracy_is_conversions_over_leads_scored_per_tier(self, client, auth, make_contact, db):
        hot_won = make_contact(score=90, tier="HOT")
        make_contact(score=85, tier="HOT")
        make_contact(score=55, tier="WARM")
        self.converted(db, hot_won, value=2000, days=20)
        report = client.get("/api/v1/analytics/model-accuracy", headers=auth("viewer")).json()
        assert (
            report["total_scored"],
            report["total_converted"],
            report["overall_conversion_rate"],
            report["model_version"],
        ) == (3, 1, 0.3333, "all")
        hot = report["tiers"][0]
        assert (
            hot["tier"],
            hot["total_leads"],
            hot["converted"],
            hot["precision"],
            hot["avg_deal_value"],
            hot["avg_days_to_close"],
        ) == ("HOT", 2, 1, 0.5, 2000.0, 20.0)

    def test_model_accuracy_can_be_limited_to_one_model_version(self, client, auth, make_contact, db):
        contact = make_contact(score=90, tier="HOT")
        self.converted(db, contact)
        viewer = auth("viewer")
        assert (
            client.get("/api/v1/analytics/model-accuracy?model_version=1.0.0", headers=viewer).json()["total_converted"]
            == 1
        )
        other = client.get("/api/v1/analytics/model-accuracy?model_version=0.0.1", headers=viewer).json()
        assert (
            other["total_converted"] == 0
            and other["total_scored"] == 0
            and other["model_version"] == "0.0.1"
            and other["tiers"] == []
        )

    def test_model_accuracy_with_nothing_scored(self, client, auth):
        report = client.get("/api/v1/analytics/model-accuracy", headers=auth("viewer")).json()
        assert report["overall_conversion_rate"] == 0.0 and report["tiers"] == []

    def test_tiers_are_ordered_hot_to_cold(self, client, auth, make_contact, db):
        for score, tier in [(10, "COLD"), (90, "HOT"), (30, "COOL"), (60, "WARM")]:
            self.converted(db, make_contact(score=score, tier=tier))
        assert [
            t["tier"] for t in client.get("/api/v1/analytics/model-accuracy", headers=auth("viewer")).json()["tiers"]
        ] == ["HOT", "WARM", "COOL", "COLD"]

    def test_score_distribution_counts_each_contacts_latest_live_score_in_equal_buckets(
        self, client, auth, make_contact, db
    ):
        for score in (5, 15, 15, 95, 100):
            make_contact(score=score, tier="HOT")
        shadow_only = make_contact(score=None)
        db.add(
            LeadScore(
                contact_id=shadow_only.id, lead_score=50, priority_tier="WARM", model_version="2.0", is_shadow=True
            )
        )
        db.commit()
        body = client.get("/api/v1/analytics/score-distribution?buckets=10", headers=auth("viewer")).json()
        counts = {b["range"]: b["count"] for b in body["buckets"]}
        assert body["total"] == 5 and len(body["buckets"]) == 10
        assert counts["0-9"] == 1 and counts["10-19"] == 2 and counts["90-100"] == 2 and sum(counts.values()) == 5

    def test_the_last_bucket_runs_to_100_whatever_the_bucket_size(self, client, auth, make_contact):
        make_contact(score=100, tier="HOT")
        body = client.get("/api/v1/analytics/score-distribution?buckets=7", headers=auth("viewer")).json()
        assert body["buckets"][-1] == {"range": "84-100", "count": 1} and body["buckets"][0]["range"] == "0-13"

    def test_an_empty_distribution(self, client, auth):
        assert client.get("/api/v1/analytics/score-distribution", headers=auth("viewer")).json() == {
            "buckets": [],
            "total": 0,
        }

    def test_only_the_latest_live_score_of_a_contact_counts(self, client, auth, make_contact, db):
        contact = make_contact(score=10, tier="COLD")
        first = db.query(LeadScore).filter_by(contact_id=contact.id).one()
        db.add(
            LeadScore(
                contact_id=contact.id,
                lead_score=80,
                priority_tier="HOT",
                model_version="1.0.0",
                scored_at=first.scored_at + timedelta(hours=1),
            )
        )
        db.commit()
        counts = {
            b["range"]: b["count"]
            for b in client.get("/api/v1/analytics/score-distribution", headers=auth("viewer")).json()["buckets"]
        }
        assert counts["80-89"] == 1 and counts["10-19"] == 0

    def test_bucket_counts_are_limited(self, client, auth):
        viewer = auth("viewer")
        assert client.get("/api/v1/analytics/score-distribution?buckets=4", headers=viewer).status_code == 422
        assert client.get("/api/v1/analytics/score-distribution?buckets=21", headers=viewer).status_code == 422


class TestModelRegistry:
    def model(self, db, version, stage="shadow", **fields):
        row = ModelRegistry(version=version, algorithm="xgboost", stage=stage, **fields)
        db.add(row)
        db.commit()
        return row

    def test_listing_and_detail_for_viewers(self, client, auth, db):
        first = self.model(db, "2.0.1", roc_auc=0.81)
        viewer = auth("viewer")
        assert [m["version"] for m in client.get("/api/v1/models", headers=viewer).json()] == ["2.0.1"]
        assert client.get(f"/api/v1/models/{first.id}", headers=viewer).json()["roc_auc"] == 0.81
        assert client.get(f"/api/v1/models/{MISSING}", headers=viewer).status_code == 404

    def test_promoting_makes_a_champion_and_archives_the_previous_one(self, client, auth, db):
        old = self.model(db, "2.0.0", stage="champion")
        new = self.model(db, "2.1.0")
        admin = auth("admin")
        assert client.post(f"/api/v1/models/{new.id}/promote", headers=admin).json() == {
            "status": "promoted",
            "version": "2.1.0",
        }
        db.expire_all()
        assert (db.get(ModelRegistry, new.id).stage, db.get(ModelRegistry, old.id).stage) == ("champion", "archived")
        assert (
            db.get(ModelRegistry, new.id).promoted_at is not None
            and db.get(ModelRegistry, old.id).archived_at is not None
        )
        assert client.post(f"/api/v1/models/{new.id}/promote", headers=admin).status_code == 409

    def test_only_admins_promote_or_shadow(self, client, auth, db):
        model = self.model(db, "2.2.0", stage="training")
        for role in ("viewer", "analyst"):
            assert client.post(f"/api/v1/models/{model.id}/promote", headers=auth(role)).status_code == 403
            assert client.post(f"/api/v1/models/{model.id}/shadow", headers=auth(role)).status_code == 403
        assert client.post(f"/api/v1/models/{model.id}/shadow", headers=auth("admin")).json()["status"] == "shadow"
        assert client.post(f"/api/v1/models/{MISSING}/promote", headers=auth("admin")).status_code == 404
        assert client.post(f"/api/v1/models/{MISSING}/shadow", headers=auth("admin")).status_code == 404

    def test_champion_feature_importances_are_sorted(self, client, auth, db):
        self.model(db, "2.3.0", stage="champion", feature_importances={"a": 1.0, "b": 9.0, "c": 5.0}, roc_auc=0.9)
        body = client.get("/api/v1/models/champion/features", headers=auth("viewer")).json()
        assert (
            list(body["importances"]) == ["b", "c", "a"] and body["model_version"] == "2.3.0" and body["roc_auc"] == 0.9
        )

    def test_with_no_champion_the_answer_says_so(self, client, auth):
        body = client.get("/api/v1/models/champion/features", headers=auth("viewer")).json()
        assert body["importances"] == {} and "no champion" in body["model_version"]


class TestObservability:
    def test_health_needs_nothing(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok" and body["timestamp"] > 0

    def test_ready_checks_the_database(self, client):
        assert client.get("/ready").json() == {"status": "ready", "db": "ok"}

    def test_a_trace_id_is_returned_and_a_good_one_is_kept(self, client):
        assert client.get("/health", headers={"X-Trace-Id": "req-123.abc"}).headers["X-Trace-Id"] == "req-123.abc"
        generated = client.get("/health").headers["X-Trace-Id"]
        assert len(generated) == 36

    @pytest.mark.parametrize("bad", ["x" * 65, "has space", "semi;colon", "<script>", "a/b"])
    def test_a_trace_id_that_is_not_an_id_is_replaced(self, client, bad):
        returned = client.get("/health", headers={"X-Trace-Id": bad}).headers["X-Trace-Id"]
        assert returned != bad and len(returned) == 36

    def test_the_query_string_is_not_logged(self, client, capsys):
        client.get("/health?code=SECRET-OAUTH-CODE&state=SECRET-STATE")
        out = capsys.readouterr().out
        assert "http_request" in out and "SECRET-OAUTH-CODE" not in out and "SECRET-STATE" not in out

    def test_the_documentation_is_off_in_production(self, monkeypatch):
        import importlib

        import app.config as config
        import app.main as main

        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("JWT_SECRET_KEY", "j" * 40)
        monkeypatch.setenv("APP_SECRET_KEY", "a" * 40)
        monkeypatch.setenv("ADMIN_PASSWORD", "a-real-admin-password")
        config.get_settings.cache_clear()
        try:
            production = importlib.reload(main)
            assert (
                production.app.docs_url is None
                and production.app.openapi_url is None
                and production.app.redoc_url is None
            )
        finally:
            monkeypatch.setenv("APP_ENV", "development")
            config.get_settings.cache_clear()
            importlib.reload(main)

    def test_cors_allows_only_the_configured_origin_and_listed_methods(self, client):
        ok = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert (
            ok.headers["access-control-allow-origin"] == "http://localhost:3000"
            and ok.headers["access-control-allow-credentials"] == "true"
        )
        other = client.options(
            "/api/v1/auth/login", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
        )
        assert "access-control-allow-origin" not in other.headers
        put = client.options(
            "/api/v1/auth/login", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "PUT"}
        )
        assert put.status_code == 400

    def test_unhandled_errors_are_a_generic_500_with_the_trace_id(self, client, monkeypatch):
        def explode(*args, **kwargs):
            raise RuntimeError("database password is hunter2")

        monkeypatch.setattr("app.main.check_db_health", explode)
        resp = client.get("/ready")
        assert (
            resp.status_code == 500
            and "hunter2" not in resp.text
            and resp.json()["detail"] == "Internal server error"
            and resp.json()["trace_id"]
        )
