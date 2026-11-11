"""Webhook events: what subscribers are told, and when (scoring and conversions fire them; the first score of a contact is a baseline)."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app import cli
from app.models.scoring import LeadScore
from app.models.webhook import WebhookDeliveryLog
from app.services import webhook_service
from app.services.webhook_service import PreviousScore, dispatch_event, score_events
from tests.conftest import BorrowedSession
from tests.test_hubspot_webhook_api import PATH as HUBSPOT_PATH
from tests.test_hubspot_webhook_api import deal, post
from tests.test_webhook_dispatch import hook
from tests.test_webhooks_api import FakeHttp
from workers.tasks import scoring as scoring_tasks
from workers.tasks.webhooks import deliver_webhook

ALL_SCORE_EVENTS = "tier_crossed,hot_lead,score_updated,demo_requested"
# enough signals for a HOT score from the formula
HOT_FEATURES = {
    "api_calls_7d": 20,
    "page_views_7d": 7,
    "email_clicks_7d": 3,
    "demo_requested": True,
    "free_trial_active": True,
    "pricing_page_visited": True,
    "integration_connected": True,
    "days_since_last_activity": 1,
}


@pytest.fixture(autouse=True)
def _dns(public_dns):
    pass


@pytest.fixture()
def queued(monkeypatch):
    """The delivery tasks that would have been queued, captured instead of sent to a broker."""
    calls: list[dict] = []
    monkeypatch.setattr(deliver_webhook, "apply_async", lambda **kwargs: calls.append(kwargs))
    return calls


def sent(db) -> list[str]:
    return sorted(row.event_type for row in db.query(WebhookDeliveryLog))


class TestScoreEvents:
    def previous(self, score=50, tier="WARM", demo=False):
        return PreviousScore(score, tier, demo)

    def test_a_first_score_is_a_baseline_and_gives_rise_to_nothing(self):
        assert score_events(None, score=95, tier="HOT", demo_requested=True) == []

    @pytest.mark.parametrize(
        ("previous", "new", "expected"),
        [
            ((50, "WARM", False), (50, "WARM", False), []),
            ((50, "WARM", False), (55, "WARM", False), ["score_updated"]),
            ((50, "WARM", False), (80, "HOT", False), ["tier_crossed", "hot_lead", "score_updated"]),
            ((80, "HOT", False), (85, "HOT", False), ["score_updated"]),  # already HOT: not a new hot lead
            ((80, "HOT", False), (60, "WARM", False), ["tier_crossed", "score_updated"]),
            ((20, "COLD", False), (30, "COOL", False), ["tier_crossed", "score_updated"]),
            ((50, "WARM", False), (50, "WARM", True), ["demo_requested"]),
            ((50, "WARM", True), (50, "WARM", True), []),  # asked before: not news
            ((50, "WARM", True), (50, "WARM", False), []),  # the signal going away is not a request
            ((50, "WARM", False), (80, "HOT", True), ["tier_crossed", "hot_lead", "score_updated", "demo_requested"]),
        ],
    )
    def test_the_events_follow_what_changed(self, previous, new, expected):
        events = score_events(PreviousScore(*previous), score=new[0], tier=new[1], demo_requested=new[2])
        assert events == expected

    def test_a_score_that_drops_a_tier_is_not_a_hot_lead(self):
        assert "hot_lead" not in score_events(self.previous(80, "HOT"), score=60, tier="WARM", demo_requested=False)


class TestScoringFiresEvents:
    def subscribe(self, db, events=ALL_SCORE_EVENTS, **kwargs):
        return hook(db, kwargs.pop("name", "listener"), events=events, **kwargs)

    def test_a_change_of_tier_tells_the_subscribers_what_changed(self, worker_db, make_contact, queued):
        self.subscribe(worker_db)
        contact = make_contact(email="ada@example.com", score=40, tier="WARM", features=HOT_FEATURES)
        result = scoring_tasks.score_single_contact(contact.id)
        assert result["tier"] == "HOT"

        assert sent(worker_db) == ["demo_requested", "hot_lead", "score_updated", "tier_crossed"]
        assert len(queued) == 4  # each delivery was queued
        crossed = worker_db.query(WebhookDeliveryLog).filter_by(event_type="tier_crossed").one()
        assert crossed.contact_id == contact.id
        assert crossed.payload["event"] == "tier_crossed" and crossed.payload["contact_id"] == contact.id
        assert crossed.payload["data"] == {
            "contact_email": "ada@example.com",
            "lead_score": result["score"],
            "previous_score": 40,
            "priority_tier": "HOT",
            "previous_tier": "WARM",
            "score_reason": crossed.payload["data"]["score_reason"],
            "recommended_action": "immediate_outreach",
            "model_version": crossed.payload["data"]["model_version"],
        }

    def test_the_first_score_of_a_contact_tells_nobody(self, worker_db, make_contact, queued):
        self.subscribe(worker_db)
        contact = make_contact(features=HOT_FEATURES)  # never scored before
        scoring_tasks.score_single_contact(contact.id)
        assert sent(worker_db) == [] and queued == []

    def test_scoring_again_with_nothing_changed_tells_nobody(self, worker_db, make_contact, queued):
        self.subscribe(worker_db)
        contact = make_contact(features=HOT_FEATURES)
        scoring_tasks.score_single_contact(contact.id)  # the baseline
        scoring_tasks.score_single_contact(contact.id)
        assert sent(worker_db) == []

    def test_a_demo_request_that_was_already_there_is_not_news(self, worker_db, make_contact, queued):
        self.subscribe(worker_db, events="demo_requested")
        contact = make_contact(score=40, tier="WARM", features=HOT_FEATURES)
        worker_db.query(LeadScore).filter_by(contact_id=contact.id).one().feature_snapshot = {"demo_requested": True}
        worker_db.commit()
        scoring_tasks.score_single_contact(contact.id)
        assert sent(worker_db) == []

    def test_a_score_is_compared_with_the_latest_live_score_not_an_older_one(self, worker_db, make_contact, queued):
        self.subscribe(worker_db, events="tier_crossed")
        contact = make_contact(score=10, tier="COLD", features=HOT_FEATURES)
        worker_db.query(LeadScore).filter_by(contact_id=contact.id).one().scored_at = datetime.now(UTC) - timedelta(
            hours=1
        )  # the older score
        worker_db.add(
            LeadScore(
                contact_id=contact.id,
                lead_score=40,
                priority_tier="WARM",
                model_version="1.0.0",
                scored_at=datetime.now(UTC) - timedelta(minutes=5),  # the newer one
            )
        )
        worker_db.commit()
        scoring_tasks.score_single_contact(contact.id)
        crossed = worker_db.query(WebhookDeliveryLog).filter_by(event_type="tier_crossed").one()
        assert crossed.payload["data"]["previous_tier"] == "WARM"

    def test_a_shadow_score_never_tells_anybody(self, worker_db, make_contact, queued):
        self.subscribe(worker_db)
        contact = make_contact(score=40, tier="WARM", features=HOT_FEATURES)
        scoring_tasks.score_single_contact(contact.id, is_shadow=True)
        assert sent(worker_db) == [] and queued == []

    def test_a_shadow_score_is_not_what_a_live_score_is_compared_with(self, worker_db, make_contact, queued):
        self.subscribe(worker_db, events="tier_crossed")
        contact = make_contact(score=40, tier="WARM", features=HOT_FEATURES)
        worker_db.add(
            LeadScore(
                contact_id=contact.id,
                lead_score=95,
                priority_tier="HOT",
                model_version="2.0.0",
                is_shadow=True,
                scored_at=datetime.now(UTC) + timedelta(hours=1),  # newer than the live one
            )
        )
        worker_db.commit()
        scoring_tasks.score_single_contact(contact.id)
        crossed = worker_db.query(WebhookDeliveryLog).filter_by(event_type="tier_crossed").one()
        assert crossed.payload["data"]["previous_tier"] == "WARM"  # not the shadow model's HOT

    def test_only_the_webhooks_subscribed_to_the_event_and_the_tier_are_told(self, worker_db, make_contact, queued):
        self.subscribe(worker_db, name="hot", events="hot_lead", tier_filter="HOT")
        self.subscribe(worker_db, name="cold-only", events="hot_lead", tier_filter="COLD")
        self.subscribe(worker_db, name="other-event", events="conversion")
        contact = make_contact(score=40, tier="WARM", features=HOT_FEATURES)
        scoring_tasks.score_single_contact(contact.id)
        rows = worker_db.query(WebhookDeliveryLog).all()
        assert [(r.webhook_id, r.event_type) for r in rows] == [(rows[0].webhook_id, "hot_lead")]

    def test_a_failure_in_notifying_costs_only_the_notification(self, worker_db, make_contact, queued, monkeypatch):
        self.subscribe(worker_db)
        contact = make_contact(score=40, tier="WARM", features=HOT_FEATURES)

        def broken(*args, **kwargs):
            raise RuntimeError("the broker is on fire")

        monkeypatch.setattr(webhook_service, "dispatch_event", broken)
        result = scoring_tasks.score_single_contact(
            contact.id
        )  # no exception, so no retry that would score the contact twice
        assert result["status"] == "ok"
        assert worker_db.query(LeadScore).filter_by(contact_id=contact.id).count() == 2  # the old score and the new one


class TestDispatchOrder:
    def test_the_delivery_rows_are_committed_before_any_worker_is_asked_to_deliver(self, db, monkeypatch):
        hook(db, "listener", events="conversion")
        order: list[str] = []
        real_commit = db.commit
        monkeypatch.setattr(db, "commit", lambda: (order.append("commit"), real_commit())[1])
        monkeypatch.setattr(deliver_webhook, "apply_async", lambda **kwargs: order.append("queue"))

        assert dispatch_event(db, "conversion", None, {"deal_value": 100}) == 1
        assert "queue" in order
        assert order.index("commit") < order.index("queue")

    def test_every_delivery_is_queued_with_its_row(self, db, queued):
        hook(db, "one", events="conversion")
        hook(db, "two", events="conversion")
        assert dispatch_event(db, "conversion", None, {}) == 2
        ids = {row.id for row in db.query(WebhookDeliveryLog)}
        assert {call["kwargs"]["delivery_log_id"] for call in queued} == ids and all(
            call["queue"] == "sync" for call in queued
        )

    def test_the_outcome_of_a_synchronous_delivery_is_saved(self, db, monkeypatch):
        hook(db, "listener", events="conversion")
        monkeypatch.setattr(webhook_service.httpx, "Client", FakeHttp())
        assert dispatch_event(db, "conversion", None, {}, async_mode=False) == 1
        db.rollback()  # anything that was not committed is gone now
        assert db.query(WebhookDeliveryLog).one().status == "success"

    def test_nothing_is_committed_or_queued_when_nobody_is_subscribed(self, db, queued):
        assert dispatch_event(db, "conversion", None, {}) == 0 and queued == []


class TestConversionsFireEvents:
    def conversion(self, contact, **fields):
        return {
            "contact_id": contact.id,
            "converted_at": datetime.now(UTC).isoformat(),
            "deal_value": 12500.0,
            **fields,
        }

    def test_recording_a_conversion_tells_the_subscribers(self, client, auth, db, make_contact, queued):
        hook(db, "listener", events="conversion")
        contact = make_contact(email="ada@example.com", score=88, tier="HOT")
        resp = client.post(
            "/api/v1/analytics/conversions",
            headers=auth("analyst"),
            json=self.conversion(contact, plan_tier="pro", crm_deal_id="D-1"),
        )
        assert resp.status_code == 201
        row = db.query(WebhookDeliveryLog).one()
        assert row.event_type == "conversion" and row.contact_id == contact.id
        assert row.payload["data"] == {
            "contact_email": "ada@example.com",
            "deal_value": 12500.0,
            "converted_at": row.payload["data"]["converted_at"],
            "source": "manual",
            "crm_deal_id": "D-1",
            "plan_tier": "pro",
            "score_at_conversion": 88,
            "tier_at_conversion": "HOT",
        }
        assert len(queued) == 1

    def test_the_tier_filter_looks_at_the_tier_the_lead_had_when_it_converted(
        self, client, auth, db, make_contact, queued
    ):
        hook(db, "warm-only", events="conversion", tier_filter="WARM")
        contact = make_contact(score=88, tier="HOT")
        client.post("/api/v1/analytics/conversions", headers=auth("analyst"), json=self.conversion(contact))
        assert sent(db) == []

    def test_a_failed_notification_does_not_fail_the_conversion(
        self, client, auth, db, make_contact, queued, monkeypatch
    ):
        hook(db, "listener", events="conversion")
        contact = make_contact()

        def broken(*args, **kwargs):
            raise RuntimeError("down")

        monkeypatch.setattr(webhook_service, "dispatch_event", broken)
        assert (
            client.post(
                "/api/v1/analytics/conversions", headers=auth("analyst"), json=self.conversion(contact)
            ).status_code
            == 201
        )

    def test_a_deal_won_in_hubspot_tells_the_subscribers_once_per_new_conversion(
        self, client, db, make_contact, queued, monkeypatch
    ):
        from app.api.v1 import analytics  # the route reads the settings object it bound when it was imported

        monkeypatch.setattr(analytics.settings, "hubspot_webhook_secret", "hubspot-client-secret")
        monkeypatch.setattr(analytics.settings, "public_api_url", "")
        hook(db, "listener", events="conversion")
        make_contact(email="ada@example.com", score=70, tier="WARM")

        first = post(client, [deal("ada@example.com", deal_id=1)])
        assert first.status_code == 200 and first.json()["created"] == 1
        assert sent(db) == ["conversion"]
        row = db.query(WebhookDeliveryLog).one()
        assert row.payload["data"]["source"] == "hubspot_webhook" and row.payload["data"]["crm_deal_id"] == "1"

        post(
            client, [deal("ada@example.com", deal_id=1)]
        )  # HubSpot retries: the duplicate is skipped, and so is its event
        assert sent(db) == ["conversion"]
        assert HUBSPOT_PATH.endswith("/hubspot")


class TestCommandLineScoring:
    """`make score` is the same scoring as the scheduled one: it keeps the signals and tells the subscribers."""

    def score(self, worker_db, monkeypatch, *args):
        monkeypatch.setattr(cli, "_get_db", lambda: BorrowedSession(worker_db))
        result = CliRunner().invoke(cli.app, ["score-leads", *args])
        assert result.exit_code == 0, result.output

    def test_a_change_of_tier_tells_the_subscribers(self, worker_db, make_contact, queued, monkeypatch):
        hook(worker_db, "listener", events=ALL_SCORE_EVENTS)
        contact = make_contact(score=40, tier="WARM", features=HOT_FEATURES)
        self.score(worker_db, monkeypatch)
        assert sent(worker_db) == ["demo_requested", "hot_lead", "score_updated", "tier_crossed"]
        assert {row.contact_id for row in worker_db.query(WebhookDeliveryLog)} == {contact.id}

    def test_the_first_pass_over_new_contacts_tells_nobody(self, worker_db, make_contact, queued, monkeypatch):
        hook(worker_db, "listener", events=ALL_SCORE_EVENTS)
        make_contact(features=HOT_FEATURES)
        make_contact(features=HOT_FEATURES)
        self.score(worker_db, monkeypatch)
        assert sent(worker_db) == [] and queued == []

    def test_a_shadow_pass_tells_nobody(self, worker_db, make_contact, queued, monkeypatch):
        hook(worker_db, "listener", events=ALL_SCORE_EVENTS)
        make_contact(score=40, tier="WARM", features=HOT_FEATURES)
        self.score(worker_db, monkeypatch, "--shadow")
        assert sent(worker_db) == []

    def test_the_scores_keep_the_signals_the_next_one_is_compared_with(self, worker_db, make_contact, monkeypatch):
        contact = make_contact(features=HOT_FEATURES)
        self.score(worker_db, monkeypatch)
        row = worker_db.query(LeadScore).filter_by(contact_id=contact.id).one()
        assert row.feature_snapshot["demo_requested"] is True and row.feature_snapshot["api_calls_7d"] == 20

    def test_a_demo_request_seen_by_the_command_line_is_not_news_to_the_scheduler(
        self, worker_db, make_contact, queued, monkeypatch
    ):
        contact = make_contact(features=HOT_FEATURES)
        self.score(worker_db, monkeypatch)  # records that the demo was already requested
        hook(worker_db, "listener", events="demo_requested")
        scoring_tasks.score_single_contact(contact.id)
        assert sent(worker_db) == []


class TestTheDocumentedVerification:
    """The README tells receivers how to check a delivery. That snippet is taken from the README and run here, so the documentation cannot drift from the code."""

    @staticmethod
    def documented_check():
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
        block = re.search(r"```python\n(import hashlib.*?def is_genuine.*?)```", readme, re.S)
        assert block, "the README no longer has the verification example"
        namespace: dict = {}
        exec(block.group(1), namespace)  # the repository's own documentation
        return namespace["is_genuine"]

    def delivery(self, db, monkeypatch):
        hook(db, "receiver", events="conversion")
        http = FakeHttp()
        monkeypatch.setattr(webhook_service.httpx, "Client", http)
        assert dispatch_event(db, "conversion", "c-1", {"deal_value": 100.0}, async_mode=False) == 1
        return http.requests[0]

    def test_a_real_delivery_passes_the_documented_check(self, db, monkeypatch):
        request = self.delivery(db, monkeypatch)
        header = request["headers"]["X-Revops-Signature"]
        assert header.startswith("sha256=")
        assert self.documented_check()("s" * 20, request["content"], header)

    def test_a_changed_body_or_another_secret_fails_it(self, db, monkeypatch):
        request = self.delivery(db, monkeypatch)
        check, header = self.documented_check(), request["headers"]["X-Revops-Signature"]
        assert not check("s" * 20, request["content"] + b" ", header)
        assert not check("another-secret-entirely", request["content"], header)
        assert not check(
            "s" * 20, request["content"], header.removeprefix("sha256=")
        )  # the prefix is part of the header

    def test_the_documented_headers_are_sent(self, db, monkeypatch):
        headers = self.delivery(db, monkeypatch)["headers"]
        assert (
            headers["X-Webhook-Event"] == "conversion"
            and headers["X-Delivery-ID"]
            and headers["Content-Type"] == "application/json"
        )
