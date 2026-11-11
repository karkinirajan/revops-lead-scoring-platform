import pytest

from app.models.webhook import Webhook, WebhookDeliveryLog
from app.services import webhook_service
from app.services.webhook_service import build_payload, dispatch_event, get_active_webhooks_for_event
from tests.test_webhooks_api import FakeHttp


@pytest.fixture(autouse=True)
def _dns(public_dns):
    pass


def hook(db, name, events="tier_crossed", tier_filter=None, status="active", url=None):
    row = Webhook(
        name=name,
        url=url or f"https://{name}.example.com/h",
        secret="s" * 20,
        events=events,
        tier_filter=tier_filter,
        status=status,
    )
    db.add(row)
    db.commit()
    return row


class TestWhoIsNotified:
    def test_only_active_webhooks_subscribed_to_the_event_are_chosen(self, db):
        hook(db, "yes")
        hook(db, "other-event", events="conversion")
        hook(db, "paused", status="paused")
        hook(db, "disabled", status="disabled")
        hook(db, "several", events="conversion, tier_crossed")
        assert {h.name for h in get_active_webhooks_for_event(db, "tier_crossed")} == {"yes", "several"}

    def test_a_tier_filter_limits_which_leads_notify(self, db):
        hook(db, "hot-only", tier_filter="HOT")
        hook(db, "hot-warm", tier_filter="hot, warm")
        hook(db, "everything")
        assert {h.name for h in get_active_webhooks_for_event(db, "tier_crossed", "HOT")} == {
            "hot-only",
            "hot-warm",
            "everything",
        }
        assert {h.name for h in get_active_webhooks_for_event(db, "tier_crossed", "warm")} == {"hot-warm", "everything"}
        assert {h.name for h in get_active_webhooks_for_event(db, "tier_crossed", "COLD")} == {"everything"}

    def test_without_a_tier_the_filter_is_not_applied(self, db):
        hook(db, "hot-only", tier_filter="HOT")
        assert [h.name for h in get_active_webhooks_for_event(db, "tier_crossed")] == ["hot-only"]

    def test_nothing_subscribed_means_nothing_chosen(self, db):
        assert get_active_webhooks_for_event(db, "tier_crossed") == []


class TestPayload:
    def test_a_payload_has_a_unique_id_the_event_and_the_time(self):
        a, b = build_payload("hot_lead", "c-1", {"score": 91}), build_payload("hot_lead", "c-1", {"score": 91})
        assert (
            a["id"] != b["id"]
            and (a["event"], a["contact_id"], a["data"]) == ("hot_lead", "c-1", {"score": 91})
            and a["timestamp"].endswith("+00:00")
        )


class TestDispatch:
    def test_nothing_subscribed_sends_nothing(self, db, monkeypatch):
        fake = FakeHttp()
        monkeypatch.setattr(webhook_service.httpx, "Client", fake)
        assert dispatch_event(db, "tier_crossed", "c-1", {}, async_mode=False) == 0 and fake.requests == []

    def test_a_synchronous_dispatch_delivers_to_every_matching_hook_and_logs_each(self, db, monkeypatch):
        one, two = hook(db, "one"), hook(db, "two")
        hook(db, "unrelated", events="conversion")
        fake = FakeHttp()
        monkeypatch.setattr(webhook_service.httpx, "Client", fake)
        assert dispatch_event(db, "tier_crossed", "c-1", {"tier": "HOT"}, tier="HOT", async_mode=False) == 2
        assert {r["url"] for r in fake.requests} == {one.url, two.url}
        logs = db.query(WebhookDeliveryLog).all()
        assert (
            len(logs) == 2
            and {log.status for log in logs} == {"success"}
            and {log.contact_id for log in logs} == {"c-1"}
        )
        db.refresh(one)
        assert (one.total_deliveries, one.successful_deliveries, one.last_triggered_at is not None) == (1, 1, True)

    def test_every_delivery_of_one_event_carries_the_same_payload_and_a_valid_signature(self, db, monkeypatch):
        import hashlib
        import hmac

        hook(db, "one")
        hook(db, "two")
        fake = FakeHttp()
        monkeypatch.setattr(webhook_service.httpx, "Client", fake)
        dispatch_event(db, "tier_crossed", "c-1", {"tier": "HOT"}, async_mode=False)
        bodies = {r["content"] for r in fake.requests}
        assert len(bodies) == 1
        for request in fake.requests:
            expected = hmac.new(b"s" * 20, request["content"], hashlib.sha256).hexdigest()
            assert (
                request["headers"]["X-Revops-Signature"] == f"sha256={expected}" and request["headers"]["X-Delivery-ID"]
            )

    def test_the_async_path_queues_one_task_per_delivery(self, db, monkeypatch):
        from workers.tasks import webhooks as webhook_tasks

        hook(db, "one")
        hook(db, "two")
        queued = []
        monkeypatch.setattr(webhook_tasks.deliver_webhook, "apply_async", lambda **kwargs: queued.append(kwargs))
        fake = FakeHttp()
        monkeypatch.setattr(webhook_service.httpx, "Client", fake)
        assert dispatch_event(db, "tier_crossed", "c-1", {}) == 2
        assert (
            len(queued) == 2
            and all(q["queue"] == "sync" and q["kwargs"]["delivery_log_id"] for q in queued)
            and fake.requests == []
        )
        assert {log.status for log in db.query(WebhookDeliveryLog)} == {"pending"}

    def test_when_the_queue_is_down_the_delivery_is_made_in_process(self, db, monkeypatch):
        from workers.tasks import webhooks as webhook_tasks

        hook(db, "one")
        monkeypatch.setattr(
            webhook_tasks.deliver_webhook,
            "apply_async",
            lambda **kwargs: (_ for _ in ()).throw(ConnectionError("broker down")),
        )
        fake = FakeHttp()
        monkeypatch.setattr(webhook_service.httpx, "Client", fake)
        assert dispatch_event(db, "tier_crossed", "c-1", {}) == 1 and len(fake.requests) == 1
        assert db.query(WebhookDeliveryLog).one().status == "success"

    def test_a_hook_without_a_secret_sends_no_signature(self, db, monkeypatch):
        row = hook(db, "unsigned")
        row.secret = None
        db.commit()
        fake = FakeHttp()
        monkeypatch.setattr(webhook_service.httpx, "Client", fake)
        dispatch_event(db, "tier_crossed", "c-1", {}, async_mode=False)
        assert "X-Revops-Signature" not in fake.requests[0]["headers"]

    def test_one_failing_receiver_does_not_stop_the_others(self, db, monkeypatch):
        hook(db, "bad", url="https://bad.example.com/h")
        hook(db, "good", url="https://good.example.com/h")
        sent = []

        class Selective(FakeHttp):
            def __call__(self, *args, **kwargs):
                client = super().__call__(*args, **kwargs)
                real_post = client.post

                def post(url, content=None, headers=None):
                    if "bad" in url:
                        raise ConnectionError("down")
                    sent.append(url)
                    return real_post(url, content=content, headers=headers)

                client.post = post
                return client

        monkeypatch.setattr(webhook_service.httpx, "Client", Selective())
        assert dispatch_event(db, "tier_crossed", "c-1", {}, async_mode=False) == 2
        assert sent == ["https://good.example.com/h"] and {log.status for log in db.query(WebhookDeliveryLog)} == {
            "success",
            "failed",
        }
