import json

import pytest

from app.config import get_settings
from app.services import ai_intelligence as ai
from app.services.ai_intelligence import GENERIC_ERROR

FEATURES = {"api_calls_7d": 30, "pricing_page_visited": True, "demo_requested": True}


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test-not-real")


class FakeCache:
    def __init__(self, stored=None, broken=False):
        self.stored, self.broken, self.writes = stored, broken, []

    def get(self, key):
        if self.broken:
            raise ConnectionError("redis down")
        return self.stored

    def setex(self, key, seconds, value):
        if self.broken:
            raise ConnectionError("redis down")
        self.writes.append((key, seconds, value))


@pytest.fixture()
def cache(monkeypatch):
    fake = FakeCache()
    monkeypatch.setattr("app.api.v1.intelligence._cache", lambda: fake)
    return fake


def report(**override):
    return {
        "contact_id": "x",
        "model": "m",
        "lead_score": 88,
        "priority_tier": "HOT",
        "analysis": "Because.",
        "input_tokens": 1,
        "output_tokens": 2,
        "generated_at": "now",
        **override,
    }


class TestSyncReport:
    def test_without_a_key_the_feature_is_off(self, client, auth, make_contact, monkeypatch):
        monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
        contact = make_contact(score=80)
        resp = client.get(f"/api/v1/contacts/{contact.id}/intelligence/sync", headers=auth("viewer"))
        assert resp.status_code == 503 and "ANTHROPIC_API_KEY" in resp.json()["detail"]

    def test_it_needs_a_login(self, client, make_contact):
        assert client.get(f"/api/v1/contacts/{make_contact().id}/intelligence/sync").status_code == 401

    def test_an_unknown_contact_is_a_404_and_nothing_is_paid_for(self, client, auth, cache, monkeypatch):
        calls = []

        async def fail(**kwargs):
            calls.append(kwargs)

        monkeypatch.setattr("app.api.v1.intelligence.get_lead_intelligence", fail)
        assert (
            client.get(
                "/api/v1/contacts/00000000-0000-0000-0000-000000000000/intelligence/sync", headers=auth("viewer")
            ).status_code
            == 404
        )
        assert calls == [] and cache.writes == []

    def test_a_report_is_generated_cached_and_returned(self, client, auth, make_contact, cache, monkeypatch):
        contact = make_contact(
            email="ada@example.com",
            first_name="Ada",
            job_title="CTO",
            score=88,
            tier="HOT",
            features=FEATURES,
            company={"name": "Acme", "size_tier": "enterprise"},
        )
        seen = {}

        async def generate(contact, features, latest_score, api_key):
            seen.update(contact=contact, features=features, score=latest_score, key=api_key)
            return report(contact_id=contact["id"])

        monkeypatch.setattr("app.api.v1.intelligence.get_lead_intelligence", generate)
        resp = client.get(f"/api/v1/contacts/{contact.id}/intelligence/sync", headers=auth("viewer"))
        assert resp.status_code == 200 and resp.json()["analysis"] == "Because."
        assert (
            seen["contact"]["company_name"] == "Acme"
            and seen["contact"]["job_title"] == "CTO"
            and seen["features"]["api_calls_7d"] == 30
        )
        assert (
            seen["score"]["lead_score"] == 88
            and seen["score"]["priority_tier"] == "HOT"
            and seen["key"] == "sk-test-not-real"
        )
        key, seconds, value = cache.writes[0]
        assert (
            key == f"intelligence:{contact.id}"
            and seconds == get_settings().ai_intelligence_cache_ttl_seconds
            and json.loads(value)["analysis"] == "Because."
        )

    def test_a_cached_report_is_returned_without_a_call(self, client, auth, make_contact, monkeypatch):
        contact = make_contact(score=70)
        monkeypatch.setattr(
            "app.api.v1.intelligence._cache", lambda: FakeCache(stored=json.dumps(report(analysis="From cache.")))
        )

        async def never(**kwargs):
            raise AssertionError("the model was called")

        monkeypatch.setattr("app.api.v1.intelligence.get_lead_intelligence", never)
        assert (
            client.get(f"/api/v1/contacts/{contact.id}/intelligence/sync", headers=auth("viewer")).json()["analysis"]
            == "From cache."
        )

    def test_a_dead_cache_does_not_stop_the_report(self, client, auth, make_contact, monkeypatch):
        contact = make_contact(score=70)
        monkeypatch.setattr("app.api.v1.intelligence._cache", lambda: FakeCache(broken=True))

        async def generate(**kwargs):
            return report()

        monkeypatch.setattr("app.api.v1.intelligence.get_lead_intelligence", generate)
        assert client.get(f"/api/v1/contacts/{contact.id}/intelligence/sync", headers=auth("viewer")).status_code == 200

    def test_a_provider_failure_is_a_502_with_a_fixed_message(
        self, client, auth, make_contact, cache, monkeypatch, capsys
    ):
        contact = make_contact(score=70)

        async def fail(**kwargs):
            raise RuntimeError("401 invalid x-api-key sk-ant-REAL-KEY-123")

        monkeypatch.setattr("app.api.v1.intelligence.get_lead_intelligence", fail)
        resp = client.get(f"/api/v1/contacts/{contact.id}/intelligence/sync", headers=auth("viewer"))
        assert resp.status_code == 502 and resp.json() == {"detail": GENERIC_ERROR} and "sk-ant" not in resp.text
        assert "ai_intelligence_failed" in capsys.readouterr().out and cache.writes == []

    ROUTES = (
        "app.api.v1.intelligence.stream_intelligence",
        "app.api.v1.intelligence.get_intelligence_sync",
        "app.api.v1.intelligence.natural_language_leads_search",
    )

    def test_every_paid_route_is_registered_with_the_configured_limit(self):
        from app.api.v1 import intelligence
        from app.middleware.rate_limit import limiter

        assert f"{get_settings().ai_intelligence_rate_limit_per_minute}/minute" == intelligence.AI_LIMIT
        for route in self.ROUTES:
            assert [str(limit.limit) for limit in limiter._route_limits[route]] == ["100000 per 1 minute"]

    def test_the_limit_is_enforced(self, client, auth, make_contact, cache, monkeypatch):
        import limits

        from app.middleware.rate_limit import limiter

        contact = make_contact(score=70)

        async def generate(**kwargs):
            return report()

        monkeypatch.setattr("app.api.v1.intelligence.get_lead_intelligence", generate)
        for limit in limiter._route_limits["app.api.v1.intelligence.get_intelligence_sync"]:
            monkeypatch.setattr(limit, "limit", limits.parse("2/minute"))
        limiter.reset()
        headers = auth("viewer")
        codes = [
            client.get(f"/api/v1/contacts/{contact.id}/intelligence/sync", headers=headers).status_code
            for _ in range(4)
        ]
        assert codes == [200, 200, 429, 429]
        limiter.reset()


class TestStream:
    def test_the_stream_is_server_sent_events(self, client, auth, make_contact, monkeypatch):
        contact = make_contact(score=88, tier="HOT", features=FEATURES)

        async def fake_stream(contact, features, latest_score, api_key):
            yield 'data: {"chunk": "Hello"}\n\n'
            yield "data: [DONE]\n\n"

        monkeypatch.setattr("app.api.v1.intelligence.stream_lead_intelligence", fake_stream)
        resp = client.get(f"/api/v1/contacts/{contact.id}/intelligence", headers=auth("viewer"))
        assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["cache-control"] == "no-cache" and resp.headers["x-accel-buffering"] == "no"
        assert resp.text == 'data: {"chunk": "Hello"}\n\ndata: [DONE]\n\n'

    def test_it_needs_a_key_a_login_and_a_known_contact(self, client, auth, make_contact, monkeypatch):
        contact = make_contact(score=70)
        assert client.get(f"/api/v1/contacts/{contact.id}/intelligence").status_code == 401
        assert (
            client.get(
                "/api/v1/contacts/00000000-0000-0000-0000-000000000000/intelligence", headers=auth("viewer")
            ).status_code
            == 404
        )
        monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
        assert client.get(f"/api/v1/contacts/{contact.id}/intelligence", headers=auth("viewer")).status_code == 503

    def test_a_contact_without_features_or_a_score_still_streams(self, client, auth, make_contact, monkeypatch):
        contact = make_contact()
        seen = {}

        async def fake_stream(contact, features, latest_score, api_key):
            seen.update(features=features, score=latest_score)
            yield "data: [DONE]\n\n"

        monkeypatch.setattr("app.api.v1.intelligence.stream_lead_intelligence", fake_stream)
        assert client.get(f"/api/v1/contacts/{contact.id}/intelligence", headers=auth("viewer")).status_code == 200
        assert seen == {"features": {}, "score": {}}


@pytest.fixture()
def search_model(monkeypatch):
    """Make the natural-language parser return fixed filters, the way a validated model answer looks."""

    def install(filters):
        async def parse(query, api_key):
            return {"raw_query": query, "filters": filters, "model": "m"}

        monkeypatch.setattr("app.api.v1.intelligence.natural_language_search", parse)

    return install


class TestNaturalLanguageSearch:
    def post(self, client, auth, **body):
        return client.post("/api/v1/leads/search", headers=auth("viewer"), json={"query": "hot fintech leads", **body})

    def test_filters_narrow_the_leads(self, client, auth, make_contact, search_model):
        make_contact(
            email="hot-fin@example.com",
            score=90,
            tier="HOT",
            company={"name": "FinCo", "industry": "Fintech", "size_tier": "enterprise"},
            features={"pricing_page_visited": True},
        )
        make_contact(
            email="hot-retail@example.com",
            score=88,
            tier="HOT",
            company={"name": "ShopCo", "industry": "Retail", "size_tier": "smb"},
            features={"pricing_page_visited": True},
        )
        make_contact(
            email="cool-fin@example.com",
            score=30,
            tier="COOL",
            company={"name": "Fin2", "industry": "Fintech", "size_tier": "smb"},
            features={"pricing_page_visited": False},
        )
        search_model({"tier": ["HOT"], "industry_contains": "fin"})
        body = self.post(client, auth).json()
        assert [r["email"] for r in body["results"]] == ["hot-fin@example.com"] and body["total"] == 1
        assert (
            body["parsed_filters"] == {"tier": ["HOT"], "industry_contains": "fin"}
            and body["query"] == "hot fintech leads"
        )

    @pytest.mark.parametrize(
        ("filters", "expected"),
        [
            ({"min_score": 60}, {"a", "b"}),
            ({"max_score": 60}, {"c", "d"}),
            ({"company_size_tier": "smb"}, {"b", "c"}),
            ({"pricing_page_visited": True}, {"a", "b"}),
            ({"demo_requested": True}, {"a"}),
            ({"free_trial_active": True}, {"b"}),
            ({"integration_connected": True}, {"a", "d"}),
            ({"days_since_last_activity_max": 5}, {"a", "b"}),
            ({"api_calls_7d_min": 50}, {"a"}),
            ({"email_clicks_7d_min": 3}, {"b"}),
            ({"tier": ["HOT", "WARM"], "pricing_page_visited": True}, {"a", "b"}),
            ({}, {"a", "b", "c", "d"}),
        ],
    )
    def test_each_filter_is_applied(self, client, auth, make_contact, search_model, filters, expected):
        rows = {
            "a": (
                90,
                "HOT",
                "enterprise",
                {
                    "pricing_page_visited": True,
                    "demo_requested": True,
                    "integration_connected": True,
                    "days_since_last_activity": 1,
                    "api_calls_7d": 100,
                },
            ),
            "b": (
                70,
                "WARM",
                "smb",
                {
                    "pricing_page_visited": True,
                    "free_trial_active": True,
                    "days_since_last_activity": 3,
                    "email_clicks_7d": 5,
                },
            ),
            "c": (40, "COOL", "smb", {"days_since_last_activity": 30}),
            "d": (20, "COLD", "mid_market", {"integration_connected": True, "days_since_last_activity": 90}),
        }
        for name, (score, tier, size, feats) in rows.items():
            make_contact(
                email=f"{name}@example.com",
                score=score,
                tier=tier,
                company={"name": name.upper(), "size_tier": size},
                features=feats,
            )
        search_model(filters)
        found = {r["email"][0] for r in self.post(client, auth).json()["results"]}
        assert found == expected

    def test_the_industry_text_is_matched_literally(self, client, auth, make_contact, search_model):
        make_contact(email="a@example.com", score=50, tier="WARM", company={"name": "A", "industry": "Health"})
        make_contact(email="b@example.com", score=50, tier="WARM", company={"name": "B", "industry": "100%_Pure"})
        search_model({"industry_contains": "%"})
        assert [r["email"] for r in self.post(client, auth).json()["results"]] == ["b@example.com"]

    def test_a_contact_whose_newest_score_is_a_shadow_one_is_still_found(
        self, client, auth, make_contact, search_model, db
    ):
        from app.models.scoring import LeadScore

        contact = make_contact(email="shadowed@example.com", score=80, tier="HOT")
        live = db.query(LeadScore).filter_by(contact_id=contact.id).one()
        db.add(
            LeadScore(
                contact_id=contact.id,
                lead_score=99,
                priority_tier="HOT",
                model_version="2.0",
                is_shadow=True,
                scored_at=live.scored_at + timedelta_hour(),
            )
        )
        db.commit()
        search_model({})
        assert [r["lead_score"] for r in self.post(client, auth).json()["results"]] == [80]

    def test_paging(self, client, auth, make_contact, search_model):
        for i in range(5):
            make_contact(email=f"s{i}@example.com", score=50 + i, tier="WARM")
        search_model({})
        body = self.post(client, auth, page=2, page_size=2).json()
        assert body["total"] == 5 and len(body["results"]) == 2 and body["page"] == 2 and body["page_size"] == 2

    @pytest.mark.parametrize(
        "override",
        [{"query": ""}, {"query": "x" * 501}, {"page": 0}, {"page_size": 0}, {"page_size": 201}, {"page": 10_001}],
    )
    def test_invalid_requests_are_a_422_before_the_model_is_called(self, client, auth, monkeypatch, override):
        async def never(*args, **kwargs):
            raise AssertionError("the model was called")

        monkeypatch.setattr("app.api.v1.intelligence.natural_language_search", never)
        assert (
            client.post("/api/v1/leads/search", headers=auth("viewer"), json={"query": "q", **override}).status_code
            == 422
        )

    def test_a_provider_failure_is_a_502_with_a_fixed_message(self, client, auth, monkeypatch):
        async def fail(query, api_key):
            raise RuntimeError("provider said: key sk-ant-123 is bad")

        monkeypatch.setattr("app.api.v1.intelligence.natural_language_search", fail)
        resp = self.post(client, auth)
        assert resp.status_code == 502 and resp.json() == {"detail": GENERIC_ERROR}

    def test_it_needs_a_key_and_a_login(self, client, auth, monkeypatch):
        assert client.post("/api/v1/leads/search", json={"query": "q"}).status_code == 401
        monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
        assert self.post(client, auth).status_code == 503

    def test_the_real_parser_output_cannot_smuggle_a_filter_in(self, client, auth, make_contact, monkeypatch):
        """End to end through the real parser: a model answer with wrong types and extra keys is reduced to what is valid."""
        make_contact(email="a@example.com", score=90, tier="HOT")
        make_contact(email="b@example.com", score=20, tier="COLD")

        class Client:
            messages = None

            def __init__(self):
                self.messages = self

            async def create(self, **kwargs):
                from types import SimpleNamespace

                text = '{"tier": "HOT", "min_score": "70", "OR 1=1": true, "max_score": 100}'
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], usage=None)

        monkeypatch.setattr(ai, "_client", lambda key: Client())
        body = self.post(client, auth).json()
        assert body["parsed_filters"] == {"max_score": 100} and body["total"] == 2


def timedelta_hour():
    from datetime import timedelta

    return timedelta(hours=1)
