"""The Celery side: every scheduled task exists, tasks are routed to queues that exist, and the connectors refuse unsafe hosts."""

import importlib
import inspect

import pytest

TASK_MODULES = ["ingest", "features", "scoring", "sync", "dlq", "webhooks"]


@pytest.fixture(scope="module")
def celery_app():
    from workers.celery_app import app

    for module in TASK_MODULES:
        importlib.import_module(f"workers.tasks.{module}")
    return app


class TestSchedule:
    def test_every_scheduled_task_exists(self, celery_app):
        missing = {
            name: entry["task"]
            for name, entry in celery_app.conf.beat_schedule.items()
            if entry["task"] not in celery_app.tasks
        }
        assert missing == {}, "the beat schedule names tasks that are not defined"

    def test_scheduled_arguments_match_the_task_signature(self, celery_app):
        for name, entry in celery_app.conf.beat_schedule.items():
            accepted = inspect.signature(celery_app.tasks[entry["task"]].run).parameters
            if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in accepted.values()):
                continue
            unknown = set(entry.get("kwargs", {})) - set(accepted)
            assert not unknown, f"{name} passes {sorted(unknown)} which {entry['task']} does not accept"

    def test_scheduled_tasks_go_to_a_queue_that_exists(self, celery_app):
        queues = {q.name for q in celery_app.conf.task_queues}
        for name, entry in celery_app.conf.beat_schedule.items():
            assert entry["options"]["queue"] in queues, name

    def test_task_routes_point_at_queues_that_exist(self, celery_app):
        queues = {q.name for q in celery_app.conf.task_queues}
        assert {route["queue"] for route in celery_app.conf.task_routes.values()} <= queues

    def test_every_task_is_json_and_acknowledged_late(self, celery_app):
        assert (
            celery_app.conf.task_serializer == "json"
            and celery_app.conf.accept_content == ["json"]
            and celery_app.conf.task_acks_late is True
        )

    def test_the_tasks_the_api_calls_exist(self, celery_app):
        for name in (
            "workers.tasks.ingest.process_raw_event",
            "workers.tasks.scoring.run_scoring_batch",
            "workers.tasks.webhooks.deliver_webhook",
        ):
            assert name in celery_app.tasks


class TestSalesforceClient:
    def make(self, url):
        from workers.connectors.salesforce import SalesforceClient

        return SalesforceClient(
            instance_url=url, access_token="token", refresh_token="refresh", client_id="id", client_secret="secret"
        )

    def test_a_salesforce_instance_is_accepted(self):
        assert self.make("https://acme.my.salesforce.com/").instance_url == "https://acme.my.salesforce.com"

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.example.com",
            "http://acme.my.salesforce.com",
            "https://acme.my.salesforce.com.evil.test",
            "",
            "https://169.254.169.254",
        ],
    )
    def test_anything_else_is_refused_before_a_token_can_be_sent(self, url):
        from app.security.urls import UnsafeUrlError

        with pytest.raises(UnsafeUrlError):
            self.make(url)

    def test_requests_carry_the_token_only_to_the_instance(self, monkeypatch):
        import httpx

        seen = []

        class FakeClient:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get(self, url, headers=None, params=None):
                seen.append((url, headers["Authorization"]))
                return httpx.Response(200, json={"records": [], "totalSize": 0}, request=httpx.Request("GET", url))

        monkeypatch.setattr("workers.connectors.salesforce.httpx.Client", FakeClient)
        client = self.make("https://acme.my.salesforce.com")
        client._throttle = lambda *a, **k: None
        client.query("SELECT Id FROM Contact")
        assert seen == [("https://acme.my.salesforce.com/services/data/v59.0/query", "Bearer token")]

    def test_a_401_refreshes_the_token_at_the_instance_and_retries(self, monkeypatch):
        import httpx

        calls = []

        class FakeClient:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get(self, url, headers=None, params=None):
                calls.append(headers["Authorization"])
                status = 401 if headers["Authorization"] == "Bearer token" else 200
                return httpx.Response(status, json={"records": [{"Id": "1"}]}, request=httpx.Request("GET", url))

        refreshed = []
        monkeypatch.setattr("workers.connectors.salesforce.httpx.Client", FakeClient)
        monkeypatch.setattr(
            "workers.connectors.salesforce.httpx.post",
            lambda url, **kw: (
                refreshed.append(url)
                or httpx.Response(200, json={"access_token": "fresh"}, request=httpx.Request("POST", url))
            ),
        )
        client = self.make("https://acme.my.salesforce.com")
        client._throttle = lambda *a, **k: None
        assert client.query("SELECT Id FROM Contact") == [{"Id": "1"}]
        assert refreshed == ["https://acme.my.salesforce.com/services/oauth2/token"] and calls == [
            "Bearer token",
            "Bearer fresh",
        ]


class TestSalesforceSync:
    def test_scores_are_pushed_only_for_contacts_with_a_salesforce_id(self):
        from workers.connectors.salesforce import SalesforceSyncService

        class Client:
            pushed = None

            def update_contact_scores(self, contacts):
                Client.pushed = contacts
                return {"success": len(contacts), "failure": 0}

        service = SalesforceSyncService(Client())
        result = service.push_scores(
            [
                {"salesforce_id": "003A", "lead_score": 90, "priority_tier": "HOT"},
                {"salesforce_id": None, "lead_score": 10, "priority_tier": "COLD"},
                {"lead_score": 5, "priority_tier": "COLD"},
            ]
        )
        assert result == (1, 0) and [c["id"] for c in Client.pushed] == ["003A"]
        assert service.push_scores([]) == (0, 0)
