from datetime import UTC

import pytest

from app.models.ingestion import RawEvent
from workers.tasks import ingest as ingest_tasks


@pytest.fixture()
def queue(monkeypatch):
    """Record what is sent to the ingest queue instead of connecting to a broker."""
    sent = []
    monkeypatch.setattr(ingest_tasks.process_raw_event, "delay", lambda **kwargs: sent.append(kwargs["raw_event_id"]))
    return sent


def event(**override):
    return {
        "source_system": "csv",
        "source_record_id": "r-1",
        "operation": "insert",
        "raw_payload": {"email": "ada@example.com"},
        **override,
    }


class TestSingle:
    def test_an_event_is_stored_and_queued(self, client, auth, queue, db):
        resp = client.post(
            "/api/v1/ingest", headers=auth("analyst"), json=event(trace_id="trace-1", event_time="2026-01-02T03:04:05Z")
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["accepted"] is True and body["message"] == "Event accepted for processing"
        row = db.get(RawEvent, body["raw_event_id"])
        assert (row.source_system, row.source_record_id, row.operation, row.trace_id, row.raw_payload) == (
            "csv",
            "r-1",
            "insert",
            "trace-1",
            {"email": "ada@example.com"},
        )
        assert (
            row.event_time.astimezone(UTC).isoformat() == "2026-01-02T03:04:05+00:00"
            and row.processed is False
            and row.quarantined is False
        )
        assert queue == [body["raw_event_id"]]

    def test_viewers_cannot_ingest(self, client, auth, queue):
        assert client.post("/api/v1/ingest", headers=auth("viewer"), json=event()).status_code == 403
        assert client.post("/api/v1/ingest", json=event()).status_code == 401
        assert queue == []

    def test_a_bad_operation_is_a_422_and_stores_nothing(self, client, auth, queue, db):
        assert client.post("/api/v1/ingest", headers=auth("analyst"), json=event(operation="upsert")).status_code == 422
        assert db.query(RawEvent).count() == 0 and queue == []

    @pytest.mark.parametrize(
        "override",
        [
            {"source_system": ""},
            {"source_system": "x" * 51},
            {"source_record_id": ""},
            {"source_record_id": "x" * 256},
            {"trace_id": "t" * 65},
            {"schema_version": 0},
            {"raw_payload": "text"},
            {"event_time": "yesterday"},
        ],
    )
    def test_invalid_fields_are_a_422(self, client, auth, queue, override):
        assert client.post("/api/v1/ingest", headers=auth("analyst"), json=event(**override)).status_code == 422

    def test_a_queue_that_is_down_does_not_lose_the_event(self, client, auth, monkeypatch, db):
        def broken(**kwargs):
            raise ConnectionError("broker unreachable")

        monkeypatch.setattr(ingest_tasks.process_raw_event, "delay", broken)
        resp = client.post("/api/v1/ingest", headers=auth("analyst"), json=event())
        assert resp.status_code == 202 and "queue is unavailable" in resp.json()["message"]
        assert db.get(RawEvent, resp.json()["raw_event_id"]) is not None

    def test_a_queue_failure_is_logged(self, client, auth, monkeypatch, capsys):
        monkeypatch.setattr(
            ingest_tasks.process_raw_event,
            "delay",
            lambda **kwargs: (_ for _ in ()).throw(ConnectionError("broker unreachable")),
        )
        client.post("/api/v1/ingest", headers=auth("analyst"), json=event())
        assert "ingest_enqueue_failed" in capsys.readouterr().out


class TestBatch:
    def test_a_batch_stores_and_queues_every_valid_event(self, client, auth, queue, db):
        events = [event(source_record_id=f"r-{i}") for i in range(3)]
        resp = client.post("/api/v1/ingest/batch", headers=auth("analyst"), json=events)
        assert resp.status_code == 202 and [r["accepted"] for r in resp.json()] == [True] * 3
        assert db.query(RawEvent).count() == 3 and sorted(queue) == sorted(r["raw_event_id"] for r in resp.json())

    def test_one_bad_operation_rejects_only_that_event(self, client, auth, queue, db):
        resp = client.post(
            "/api/v1/ingest/batch",
            headers=auth("analyst"),
            json=[event(), event(operation="explode"), event(source_record_id="r-3")],
        )
        results = resp.json()
        assert [r["accepted"] for r in results] == [True, False, True]
        assert results[1]["raw_event_id"] == "" and "Invalid operation: explode" in results[1]["message"]
        assert db.query(RawEvent).count() == 2 and len(queue) == 2

    def test_the_rejection_message_does_not_echo_a_huge_operation(self, client, auth, queue):
        resp = client.post("/api/v1/ingest/batch", headers=auth("analyst"), json=[event(operation="x" * 5000)])
        assert len(resp.json()[0]["message"]) < 100

    def test_500_events_are_allowed_and_501_are_not(self, client, auth, queue, db):
        assert (
            client.post(
                "/api/v1/ingest/batch",
                headers=auth("analyst"),
                json=[event(source_record_id=str(i)) for i in range(500)],
            ).status_code
            == 202
        )
        too_many = client.post(
            "/api/v1/ingest/batch", headers=auth("analyst"), json=[event(source_record_id=str(i)) for i in range(501)]
        )
        assert too_many.status_code == 400 and "500" in too_many.json()["detail"] and db.query(RawEvent).count() == 500

    def test_an_empty_batch_is_fine(self, client, auth, queue):
        resp = client.post("/api/v1/ingest/batch", headers=auth("analyst"), json=[])
        assert resp.status_code == 202 and resp.json() == []

    def test_viewers_cannot_ingest_a_batch(self, client, auth, queue):
        assert client.post("/api/v1/ingest/batch", headers=auth("viewer"), json=[event()]).status_code == 403

    def test_a_queue_failure_still_stores_the_batch(self, client, auth, monkeypatch, db):
        monkeypatch.setattr(
            ingest_tasks.process_raw_event, "delay", lambda **kwargs: (_ for _ in ()).throw(ConnectionError("down"))
        )
        resp = client.post(
            "/api/v1/ingest/batch", headers=auth("analyst"), json=[event(), event(source_record_id="r-2")]
        )
        assert resp.status_code == 202 and db.query(RawEvent).count() == 2
