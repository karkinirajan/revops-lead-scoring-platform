"""The worker pipeline against a real database: ingest → features → scoring, the run bookkeeping, and webhook delivery tasks."""

from datetime import UTC, datetime, timedelta

import pytest
from celery.exceptions import Retry

from app.models.company import Company
from app.models.contact import Contact, ContactFeature
from app.models.ingestion import RawEvent
from app.models.scoring import LeadScore, ScoringRun
from app.models.webhook import Webhook, WebhookDeliveryLog
from app.services import webhook_service
from tests.test_webhooks_api import FakeHttp
from workers.tasks import features as feature_tasks
from workers.tasks import ingest as ingest_tasks
from workers.tasks import scoring as scoring_tasks
from workers.tasks import webhooks as webhook_tasks


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value


@pytest.fixture()
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(ingest_tasks, "_get_redis", lambda: fake)
    return fake


@pytest.fixture()
def recomputed(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ingest_tasks.recompute_contact_features, "delay", lambda **kwargs: calls.append(kwargs["contact_id"])
    )
    return calls


def raw_event(db, payload=None, *, source="hubspot", record="rec-1", operation="insert", **fields):
    event = RawEvent(
        source_system=source,
        source_record_id=record,
        operation=operation,
        schema_version=1,
        raw_payload={
            "id": "900",
            "properties": {"email": "Ada@Example.com", "firstname": "Ada", "lastname": "Lovelace", "jobtitle": "CTO"},
        }
        if payload is None
        else payload,
        **fields,
    )
    db.add(event)
    db.commit()
    return event


class TestIngest:
    def test_an_event_becomes_a_contact_and_triggers_features(self, worker_db, redis, recomputed):
        event = raw_event(worker_db)
        result = ingest_tasks.process_raw_event(event.id)
        contact = worker_db.query(Contact).one()
        assert result == {"status": "ok", "raw_event_id": event.id, "contact_id": contact.id}
        assert (
            contact.email,
            contact.first_name,
            contact.last_name,
            contact.job_title,
            contact.source_system,
            contact.hubspot_contact_id,
        ) == ("ada@example.com", "Ada", "Lovelace", "CTO", "hubspot", "900")
        assert (
            worker_db.get(RawEvent, event.id).processed is True
            and worker_db.get(RawEvent, event.id).processed_at is not None
        )
        assert recomputed == [contact.id] and redis.store

    def test_the_same_event_twice_is_processed_once(self, worker_db, redis, recomputed):
        event = raw_event(worker_db)
        ingest_tasks.process_raw_event(event.id)
        assert ingest_tasks.process_raw_event(event.id)["status"] == "duplicate"
        assert worker_db.query(Contact).count() == 1 and len(recomputed) == 1

    def test_a_later_event_for_the_same_record_updates_the_contact(self, worker_db, redis, recomputed):
        ingest_tasks.process_raw_event(raw_event(worker_db).id)
        update = raw_event(
            worker_db,
            {
                "id": "900",
                "properties": {"email": "ada@example.com", "firstname": "Augusta", "lifecyclestage": "customer"},
            },
            operation="update",
        )
        ingest_tasks.process_raw_event(update.id)
        contact = worker_db.query(Contact).one()
        assert (contact.first_name, contact.last_name, contact.lifecycle_stage) == (
            "Augusta",
            "Lovelace",
            "customer",
        )  # a field not sent is kept

    def test_an_unknown_event_is_not_found(self, worker_db, redis):
        assert ingest_tasks.process_raw_event("00000000-0000-0000-0000-000000000000") == {"status": "not_found"}

    def test_a_quarantined_event_is_left_alone(self, worker_db, redis):
        event = raw_event(worker_db, quarantined=True)
        assert (
            ingest_tasks.process_raw_event(event.id) == {"status": "quarantined"}
            and worker_db.query(Contact).count() == 0
        )

    def test_an_event_that_breaks_the_contract_is_quarantined_with_the_reasons(self, worker_db, redis):
        event = raw_event(worker_db, {}, operation="explode")
        result = ingest_tasks.process_raw_event(event.id)
        assert result["status"] == "quarantined" and set(result["reasons"]) == {
            "invalid operation: explode",
            "empty raw_payload",
        }
        row = worker_db.get(RawEvent, event.id)
        assert (
            row.quarantined is True
            and "empty raw_payload" in row.quarantine_reason
            and worker_db.query(Contact).count() == 0
        )

    def test_a_delete_does_not_create_or_change_a_contact(self, worker_db, redis, recomputed):
        ingest_tasks.process_raw_event(raw_event(worker_db).id)
        before = worker_db.query(Contact).one().first_name
        gone = raw_event(
            worker_db,
            {"id": "900", "properties": {"email": "ada@example.com", "firstname": "Changed"}},
            operation="delete",
        )
        result = ingest_tasks.process_raw_event(gone.id)
        assert (
            result["contact_id"] is None
            and worker_db.query(Contact).one().first_name == before
            and worker_db.get(RawEvent, gone.id).processed is True
        )

    def test_a_delete_for_an_unknown_record_creates_nothing(self, worker_db, redis):
        ingest_tasks.process_raw_event(raw_event(worker_db, operation="delete").id)
        assert worker_db.query(Contact).count() == 0

    @pytest.mark.parametrize("email", ["", "not-an-email", "x" * 260 + "@example.com"])
    def test_an_unusable_email_creates_no_contact_but_does_not_fail(self, worker_db, redis, email):
        event = raw_event(worker_db, {"id": "1", "properties": {"email": email}})
        assert ingest_tasks.process_raw_event(event.id)["contact_id"] is None
        assert worker_db.query(Contact).count() == 0 and worker_db.get(RawEvent, event.id).processed is True

    def test_an_unknown_source_is_processed_without_a_contact(self, worker_db, redis):
        event = raw_event(worker_db, source="mystery")
        assert ingest_tasks.process_raw_event(event.id)["contact_id"] is None and worker_db.query(Contact).count() == 0

    def test_a_company_is_created_once_per_domain(self, worker_db, redis, recomputed):
        for n in (1, 2):
            payload = {"id": str(n), "email": f"p{n}@acme.test", "company": "Acme", "domain": "acme.test"}
            ingest_tasks.process_raw_event(raw_event(worker_db, payload, record=f"r{n}").id)
        company = worker_db.query(Company).one()
        assert (company.name, company.domain) == ("Acme", "acme.test") and {
            c.company_id for c in worker_db.query(Contact)
        } == {company.id}

    def test_flat_payloads_work_like_nested_ones(self, worker_db, redis, recomputed):
        ingest_tasks.process_raw_event(
            raw_event(
                worker_db, {"email": "flat@example.com", "first_name": "Flat", "job_title": "Dev"}, source="csv"
            ).id
        )
        contact = worker_db.query(Contact).one()
        assert (contact.first_name, contact.job_title, contact.hubspot_contact_id) == ("Flat", "Dev", None)


def add_event(db, contact, event_type, *, days_ago=0, **payload):
    db.add(
        RawEvent(
            source_system=contact.source_system,
            source_record_id=contact.source_record_id,
            operation="insert",
            schema_version=1,
            event_time=datetime.now(UTC) - timedelta(days=days_ago, hours=1),
            raw_payload={"event_type": event_type, **payload},
            processed=True,
        )
    )


class TestFeatures:
    def test_signals_are_counted_within_their_windows(self, worker_db, make_contact):
        contact = make_contact()
        for days in (0, 3, 6):
            add_event(worker_db, contact, "api_call", days_ago=days)
        for days in (10, 29):
            add_event(worker_db, contact, "api_call", days_ago=days)
        add_event(worker_db, contact, "api_call", days_ago=45)
        add_event(worker_db, contact, "page_view", page="/docs")
        add_event(worker_db, contact, "page_view", page="/pricing")
        add_event(worker_db, contact, "page_view", page="/old", days_ago=20)
        add_event(worker_db, contact, "email_open")
        add_event(worker_db, contact, "email_open", days_ago=9)
        add_event(worker_db, contact, "email_click")
        add_event(worker_db, contact, "demo_request", days_ago=40)
        worker_db.commit()
        feature_tasks.compute_features_for_contact(contact.id)
        f = worker_db.query(ContactFeature).one()
        assert (f.api_calls_7d, f.api_calls_30d, f.page_views_7d, f.email_opens_7d, f.email_clicks_7d) == (
            3,
            5,
            2,
            1,
            1,
        )
        assert f.pricing_page_visited is True and f.demo_requested is True and f.computed_at is not None

    def test_unprocessed_events_and_other_contacts_events_do_not_count(self, worker_db, make_contact):
        mine, other = make_contact(), make_contact()
        add_event(worker_db, other, "api_call")
        pending = RawEvent(
            source_system=mine.source_system,
            source_record_id=mine.source_record_id,
            operation="insert",
            schema_version=1,
            event_time=datetime.now(UTC),
            raw_payload={"event_type": "api_call"},
            processed=False,
        )
        worker_db.add(pending)
        worker_db.commit()
        feature_tasks.compute_features_for_contact(mine.id)
        assert worker_db.query(ContactFeature).filter_by(contact_id=mine.id).one().api_calls_7d == 0

    def test_days_since_last_activity_prefers_the_contacts_own_date(self, worker_db, make_contact):
        contact = make_contact(last_activity_at=datetime.now(UTC) - timedelta(days=4, hours=1))
        add_event(worker_db, contact, "api_call", days_ago=1)
        worker_db.commit()
        feature_tasks.compute_features_for_contact(contact.id)
        assert worker_db.query(ContactFeature).one().days_since_last_activity == 4

    def test_without_an_activity_date_the_newest_event_is_used(self, worker_db, make_contact):
        contact = make_contact()
        add_event(worker_db, contact, "api_call", days_ago=2)
        worker_db.commit()
        feature_tasks.compute_features_for_contact(contact.id)
        assert worker_db.query(ContactFeature).one().days_since_last_activity == 2

    def test_a_contact_with_no_activity_at_all_is_999_days_idle(self, worker_db, make_contact):
        contact = make_contact()
        feature_tasks.compute_features_for_contact(contact.id)
        f = worker_db.query(ContactFeature).one()
        assert f.days_since_last_activity == 999 and f.api_calls_7d == 0 and f.pricing_page_visited is False

    def test_recomputing_updates_the_same_row(self, worker_db, make_contact):
        contact = make_contact()
        feature_tasks.compute_features_for_contact(contact.id)
        add_event(worker_db, contact, "api_call")
        worker_db.commit()
        feature_tasks.compute_features_for_contact(contact.id)
        rows = worker_db.query(ContactFeature).all()
        assert len(rows) == 1 and rows[0].api_calls_7d == 1

    def test_an_unknown_contact_is_ignored(self, worker_db):
        feature_tasks.compute_features_for_contact("00000000-0000-0000-0000-000000000000")
        assert worker_db.query(ContactFeature).count() == 0

    def test_the_task_wrapper_computes_features(self, worker_db, make_contact):
        feature_tasks.compute_features_for_contact_task(make_contact().id)
        assert worker_db.query(ContactFeature).count() == 1

    def test_recompute_all_dispatches_one_task_per_contact(self, worker_db, make_contact, monkeypatch):
        for _ in range(3):
            make_contact()
        sent = []
        monkeypatch.setattr(
            feature_tasks.compute_features_for_contact_task, "delay", lambda **kwargs: sent.append(kwargs["contact_id"])
        )
        assert feature_tasks.recompute_all_features(batch_size=2) == {"dispatched": 3} and len(set(sent)) == 3

    def test_the_ingest_wrapper_recomputes_features(self, worker_db, make_contact):
        ingest_tasks.recompute_contact_features(make_contact().id)
        assert worker_db.query(ContactFeature).count() == 1


class TestScoringTasks:
    def test_a_contact_with_features_is_scored_and_the_score_saved(self, worker_db, make_contact):
        contact = make_contact(
            features={
                "api_calls_7d": 200,
                "pricing_page_visited": True,
                "demo_requested": True,
                "free_trial_active": True,
                "integration_connected": True,
                "days_since_last_activity": 0,
            }
        )
        result = scoring_tasks.score_single_contact(contact.id)
        saved = worker_db.query(LeadScore).filter_by(contact_id=contact.id).one()
        assert (
            result["status"] == "ok" and result["score"] == saved.lead_score and result["tier"] == saved.priority_tier
        )
        assert (
            saved.lead_score > 50
            and saved.is_shadow is False
            and saved.score_reason
            and saved.feature_snapshot["demo_requested"] is True
            and saved.scored_at
        )

    def test_a_contact_with_no_features_is_scored_as_idle(self, worker_db, make_contact):
        contact = make_contact()
        assert scoring_tasks.score_single_contact(contact.id)["tier"] == "COLD"
        assert worker_db.query(LeadScore).filter_by(contact_id=contact.id).one().feature_freshness_at is None

    def test_a_shadow_score_is_marked(self, worker_db, make_contact):
        contact = make_contact()
        scoring_tasks.score_single_contact(contact.id, is_shadow=True)
        assert worker_db.query(LeadScore).one().is_shadow is True

    def test_an_unknown_contact_is_not_found(self, worker_db):
        assert scoring_tasks.score_single_contact("00000000-0000-0000-0000-000000000000")["status"] == "not_found"

    def test_the_ml_model_is_used_when_there_is_a_champion(self, worker_db, make_contact, monkeypatch):
        from app.services.scoring_engine import ScoreResult

        contact = make_contact()
        monkeypatch.setattr("app.services.ml_scoring_engine.get_champion_model_path", lambda: ("model.json", "2.9.9"))
        monkeypatch.setattr(
            "app.services.ml_scoring_engine.score_contact_ml",
            lambda fv, path, version: ScoreResult(
                lead_score=77,
                priority_tier="HOT",
                score_reason="ML",
                feature_contributions={},
                model_version=version,
                recommended_action="call",
            ),
        )
        scoring_tasks.score_single_contact(contact.id, use_ml_model=True)
        saved = worker_db.query(LeadScore).one()
        assert (saved.lead_score, saved.model_version) == (77, "2.9.9")

    def test_without_a_champion_the_deterministic_model_is_used_even_if_ml_was_asked_for(
        self, worker_db, make_contact, monkeypatch
    ):
        contact = make_contact()
        monkeypatch.setattr("app.services.ml_scoring_engine.get_champion_model_path", lambda: None)
        scoring_tasks.score_single_contact(contact.id, use_ml_model=True)
        assert worker_db.query(LeadScore).one().model_version == "1.0.0"


class TestScoringRuns:
    def run(self, db, **fields):
        fields.setdefault("total_contacts", 2)
        run = ScoringRun(model_version="1.0.0", status="running", **fields)
        db.add(run)
        db.commit()
        return run

    def test_a_run_is_completed_when_every_contact_is_scored(self, worker_db, make_contact):
        run = self.run(worker_db)
        first, second = make_contact(), make_contact()
        scoring_tasks.score_single_contact(first.id, run_id=run.id)
        worker_db.refresh(run)
        assert (run.status, run.scored_count, run.completed_at) == ("running", 1, None)
        scoring_tasks.score_single_contact(second.id, run_id=run.id)
        worker_db.refresh(run)
        assert (
            (run.status, run.scored_count, run.error_count) == ("completed", 2, 0)
            and run.completed_at
            and run.duration_seconds >= 0
        )

    def test_failures_are_counted_and_a_mixed_run_is_partial(self, worker_db, make_contact):
        run = self.run(worker_db)
        scoring_tasks.score_single_contact(make_contact().id, run_id=run.id)
        scoring_tasks.score_single_contact.on_failure(
            RuntimeError("x"), "task-1", (), {"contact_id": "gone", "run_id": run.id}, None
        )
        worker_db.refresh(run)
        assert (run.status, run.scored_count, run.error_count) == ("partial", 1, 1)

    def test_a_run_where_everything_failed_is_failed(self, worker_db):
        run = self.run(worker_db)
        for _ in range(2):
            scoring_tasks.score_single_contact.on_failure(
                RuntimeError("x"), "t", ("c", run.id), {}, None
            )  # run id given positionally
        worker_db.refresh(run)
        assert (run.status, run.scored_count, run.error_count) == ("failed", 0, 2)

    def test_a_failure_without_a_run_is_ignored(self, worker_db):
        scoring_tasks.score_single_contact.on_failure(RuntimeError("x"), "t", (), {"contact_id": "c"}, None)
        assert worker_db.query(ScoringRun).count() == 0

    def test_a_finished_run_is_not_finished_twice(self, worker_db, make_contact):
        run = self.run(worker_db, total_contacts=1)
        scoring_tasks.score_single_contact(make_contact().id, run_id=run.id)
        worker_db.refresh(run)
        finished = run.completed_at
        scoring_tasks.score_single_contact(make_contact().id, run_id=run.id)  # one more than expected
        worker_db.refresh(run)
        assert run.status == "completed" and run.completed_at == finished and run.scored_count == 2

    def test_scoring_without_a_run_keeps_no_books(self, worker_db, make_contact):
        scoring_tasks.score_single_contact(make_contact().id)
        assert worker_db.query(ScoringRun).count() == 0

    def test_the_batch_creates_a_run_and_fans_out_one_task_per_contact(self, worker_db, make_contact, monkeypatch):
        sent = []
        monkeypatch.setattr(scoring_tasks.score_single_contact, "delay", lambda **kwargs: sent.append(kwargs))
        ids = {make_contact().id for _ in range(3)}
        result = scoring_tasks.run_scoring_batch(is_shadow=True, use_ml_model=True)
        run = worker_db.get(ScoringRun, result["run_id"])
        assert (
            result["status"] == "dispatched"
            and result["total"] == 3
            and (run.status, run.total_contacts, run.is_shadow, run.triggered_by) == ("running", 3, True, "scheduler")
        )
        assert {s["contact_id"] for s in sent} == ids and all(
            s["run_id"] == run.id and s["is_shadow"] is True and s["use_ml_model"] is True for s in sent
        )

    def test_the_batch_takes_over_the_run_the_api_created(self, worker_db, make_contact, monkeypatch):
        monkeypatch.setattr(scoring_tasks.score_single_contact, "delay", lambda **kwargs: None)
        run = ScoringRun(model_version="1.0.0", status="pending", triggered_by="api")
        worker_db.add(run)
        worker_db.commit()
        make_contact()
        result = scoring_tasks.run_scoring_batch(run_id=run.id)
        worker_db.refresh(run)
        assert result["run_id"] == run.id and (run.status, run.total_contacts, run.triggered_by) == (
            "running",
            1,
            "api",
        )

    def test_the_batch_can_be_limited_to_a_company_size(self, worker_db, make_contact, monkeypatch):
        sent = []
        monkeypatch.setattr(
            scoring_tasks.score_single_contact, "delay", lambda **kwargs: sent.append(kwargs["contact_id"])
        )
        make_contact(company={"name": "Big", "size_tier": "enterprise"})
        small = make_contact(company={"name": "Small", "size_tier": "smb"})
        make_contact()  # no company
        assert scoring_tasks.run_scoring_batch(filter_segment="smb")["total"] == 1 and sent == [small.id]

    def test_a_batch_with_nothing_to_score_is_completed_at_once(self, worker_db, monkeypatch):
        sent = []
        monkeypatch.setattr(scoring_tasks.score_single_contact, "delay", lambda **kwargs: sent.append(kwargs))
        result = scoring_tasks.run_scoring_batch()
        run = worker_db.get(ScoringRun, result["run_id"])
        assert (
            sent == []
            and (run.status, run.total_contacts) == ("completed", 0)
            and run.completed_at
            and run.duration_seconds >= 0
        )

    def test_a_whole_run_through_the_batch_ends_completed(self, worker_db, make_contact, monkeypatch):
        sent = []
        monkeypatch.setattr(scoring_tasks.score_single_contact, "delay", lambda **kwargs: sent.append(kwargs))
        for _ in range(3):
            make_contact()
        result = scoring_tasks.run_scoring_batch()
        for kwargs in sent:
            scoring_tasks.score_single_contact(**kwargs)
        run = worker_db.get(ScoringRun, result["run_id"])
        worker_db.refresh(run)
        assert (run.status, run.scored_count, run.error_count) == ("completed", 3, 0)
        assert worker_db.query(LeadScore).count() == 3

    def test_retraining_that_has_too_little_data_is_skipped_not_failed(self, monkeypatch):
        def too_few(**kwargs):
            raise ValueError("only 3 labelled rows, need 200")

        monkeypatch.setattr("workers.training.train_model.train", too_few)
        assert scoring_tasks.retrain_ml_model() == {"status": "skipped", "reason": "only 3 labelled rows, need 200"}

    def test_retraining_reports_the_new_version(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            "workers.training.train_model.train", lambda **kwargs: seen.update(kwargs) or "2.20261110.0900"
        )
        assert scoring_tasks.retrain_ml_model(min_rows=50, promote=True) == {
            "status": "ok",
            "version": "2.20261110.0900",
        }
        assert seen == {"min_rows": 50, "shadow": False, "promote": True}

    def test_other_retraining_errors_are_raised(self, monkeypatch):
        def broken(**kwargs):
            raise RuntimeError("xgboost exploded")

        monkeypatch.setattr("workers.training.train_model.train", broken)
        with pytest.raises(RuntimeError):
            scoring_tasks.retrain_ml_model()


@pytest.fixture()
def hook(worker_db, public_dns):
    row = Webhook(name="h", url="https://hooks.example.com/x", secret="s" * 20, events="tier_crossed", status="active")
    worker_db.add(row)
    worker_db.commit()
    return row


def delivery(db, hook, **fields):
    row = WebhookDeliveryLog(
        webhook_id=hook.id, event_type="tier_crossed", payload={"id": "e1", "data": {}}, status="pending", **fields
    )
    db.add(row)
    db.commit()
    return row


class TestWebhookTasks:
    def test_a_delivery_is_made_and_logged(self, worker_db, hook, monkeypatch):
        fake = FakeHttp()
        monkeypatch.setattr(webhook_service.httpx, "Client", fake)
        log = delivery(worker_db, hook)
        assert webhook_tasks.deliver_webhook(log.id) == {"status": "success", "http_status": 200}
        worker_db.refresh(log)
        assert (log.status, log.attempt_number) == ("success", 1) and fake.requests[0]["url"] == hook.url

    def test_a_failed_delivery_is_retried_after_the_first_delay(self, worker_db, hook, monkeypatch):
        monkeypatch.setattr(webhook_service.httpx, "Client", FakeHttp(status=503))
        asked = {}

        def fake_retry(**kwargs):
            asked.update(kwargs)
            raise Retry()

        monkeypatch.setattr(webhook_tasks.deliver_webhook, "retry", fake_retry)
        log = delivery(worker_db, hook)
        with pytest.raises(Retry):
            webhook_tasks.deliver_webhook(log.id)
        assert asked == {"countdown": webhook_service.RETRY_DELAYS[0]}
        worker_db.refresh(log)
        assert log.status == "failed" and log.http_status_code == 503

    def test_an_already_delivered_event_is_not_sent_again(self, worker_db, hook, monkeypatch):
        fake = FakeHttp()
        monkeypatch.setattr(webhook_service.httpx, "Client", fake)
        log = delivery(worker_db, hook)
        log.status = "success"
        worker_db.commit()
        assert webhook_tasks.deliver_webhook(log.id) == {"status": "already_delivered"} and fake.requests == []

    def test_an_unknown_delivery_is_not_found(self, worker_db):
        assert webhook_tasks.deliver_webhook("00000000-0000-0000-0000-000000000000") == {"status": "not_found"}

    def test_the_sweep_requeues_recent_failures_that_have_attempts_left(self, worker_db, hook, monkeypatch):
        queued = []
        monkeypatch.setattr(
            webhook_tasks.deliver_webhook,
            "apply_async",
            lambda **kwargs: queued.append(kwargs["kwargs"]["delivery_log_id"]),
        )
        recent = delivery(worker_db, hook, attempt_number=1)
        recent.status = "failed"
        exhausted = delivery(worker_db, hook, attempt_number=webhook_service.MAX_ATTEMPTS)
        exhausted.status = "failed"
        old = delivery(worker_db, hook, attempt_number=1)
        old.status = "failed"
        old.created_at = datetime.now(UTC) - timedelta(hours=30)
        ok = delivery(worker_db, hook)
        ok.status = "success"
        worker_db.commit()
        result = webhook_tasks.retry_failed_webhooks()
        assert queued == [recent.id] and result["queued"] == 1
