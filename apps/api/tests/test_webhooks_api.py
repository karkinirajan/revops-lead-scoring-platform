import httpx
import pytest

from app.models.webhook import Webhook, WebhookDeliveryLog
from app.services import webhook_service

URL = "https://hooks.example.com/revops"


@pytest.fixture(autouse=True)
def _dns(public_dns):
    """Every host resolves to a public address unless a test says otherwise."""


def create(client, headers, **override):
    body = {"name": "Slack bridge", "url": URL, "events": "tier_crossed,hot_lead", **override}
    return client.post("/api/v1/webhooks", headers=headers, json=body)


class FakeHttp:
    """Replaces httpx.Client in the delivery code and records the requests."""

    def __init__(self, status=200, text="ok", error=None):
        self.status, self.text, self.error, self.requests = status, text, error, []

    def __call__(self, *args, **kwargs):
        outer = self
        outer.client_kwargs = kwargs

        class _Client:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def post(self, url, content=None, headers=None):
                if outer.error:
                    raise outer.error
                outer.requests.append({"url": url, "content": content, "headers": headers})
                return httpx.Response(outer.status, text=outer.text, request=httpx.Request("POST", url))

        return _Client()


class TestPermissions:
    def test_a_viewer_cannot_create_change_or_delete_webhooks(self, client, auth, make_user):
        viewer = auth("viewer")
        assert create(client, viewer).status_code == 403
        hook = create(client, auth("analyst")).json()
        assert client.patch(f"/api/v1/webhooks/{hook['id']}", headers=viewer, json={"name": "x"}).status_code == 403
        assert client.delete(f"/api/v1/webhooks/{hook['id']}", headers=viewer).status_code == 403
        assert client.post(f"/api/v1/webhooks/{hook['id']}/test", headers=viewer, json={}).status_code == 403

    def test_a_viewer_can_still_read_them(self, client, auth):
        create(client, auth("analyst"))
        assert client.get("/api/v1/webhooks", headers=auth("viewer")).status_code == 200

    def test_no_token_is_a_401(self, client):
        assert client.get("/api/v1/webhooks").status_code == 401
        assert client.post("/api/v1/webhooks", json={}).status_code == 401


class TestCreate:
    def test_the_signing_secret_is_generated_and_shown_once(self, client, auth, db):
        analyst = auth("analyst")
        created = create(client, analyst)
        assert created.status_code == 201
        secret = created.json()["secret"]
        assert len(secret) >= 32
        assert db.get(Webhook, created.json()["id"]).secret == secret  # what the deliveries are signed with
        for response in (
            client.get(f"/api/v1/webhooks/{created.json()['id']}", headers=analyst),
            client.get("/api/v1/webhooks", headers=analyst),
        ):
            assert secret not in response.text

    def test_a_given_secret_is_kept(self, client, auth):
        created = create(client, auth("analyst"), secret="my-own-signing-secret-1234")
        assert created.json()["secret"] == "my-own-signing-secret-1234"

    def test_two_webhooks_get_different_secrets(self, client, auth):
        analyst = auth("analyst")
        assert create(client, analyst).json()["secret"] != create(client, analyst).json()["secret"]

    def test_a_short_secret_is_a_422(self, client, auth):
        assert create(client, auth("analyst"), secret="short").status_code == 422

    @pytest.mark.parametrize(
        "url",
        [
            "http://hooks.example.com/x",
            "ftp://hooks.example.com/",
            "https://user:pw@hooks.example.com/",
            "not a url",
            "file:///etc/passwd",
        ],
    )
    def test_an_unsuitable_url_is_a_422(self, client, auth, url):
        resp = create(client, auth("analyst"), url=url)
        assert resp.status_code == 422 and "Invalid webhook URL" in resp.json()["detail"]

    @pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "10.1.2.3", "192.168.0.10", "::1"])
    def test_a_host_that_resolves_inward_is_a_422(self, client, auth, monkeypatch, address):
        monkeypatch.setattr("app.security.urls.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (address, 0))])
        resp = create(client, auth("analyst"), url="https://internal.example.com/")
        assert resp.status_code == 422 and address not in resp.text

    def test_an_unknown_event_is_a_422(self, client, auth):
        assert create(client, auth("analyst"), events="tier_crossed,exploded").status_code == 422

    def test_an_empty_name_or_a_huge_url_is_a_422(self, client, auth):
        assert create(client, auth("analyst"), name="").status_code == 422
        assert create(client, auth("analyst"), url="https://a.example/" + "x" * 3000).status_code == 422

    def test_the_creator_is_recorded(self, client, auth, db):
        created = create(client, auth("analyst")).json()
        assert db.get(Webhook, created["id"]).created_by is not None


class TestUpdate:
    def test_fields_can_be_changed(self, client, auth):
        analyst = auth("analyst")
        hook = create(client, analyst).json()
        resp = client.patch(
            f"/api/v1/webhooks/{hook['id']}",
            headers=analyst,
            json={"name": "Renamed", "status": "paused", "tier_filter": "HOT"},
        )
        assert resp.status_code == 200
        assert (resp.json()["name"], resp.json()["status"], resp.json()["tier_filter"]) == ("Renamed", "paused", "HOT")

    def test_a_new_url_is_checked_too(self, client, auth, monkeypatch):
        analyst = auth("analyst")
        hook = create(client, analyst).json()
        monkeypatch.setattr("app.security.urls.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.9", 0))])
        resp = client.patch(
            f"/api/v1/webhooks/{hook['id']}", headers=analyst, json={"url": "https://now-internal.example.com/"}
        )
        assert resp.status_code == 422
        assert client.get(f"/api/v1/webhooks/{hook['id']}", headers=analyst).json()["url"] == URL

    @pytest.mark.parametrize("field", ["name", "url", "status"])
    def test_required_fields_cannot_be_cleared(self, client, auth, field):
        analyst = auth("analyst")
        hook = create(client, analyst).json()
        before = hook[field]
        resp = client.patch(f"/api/v1/webhooks/{hook['id']}", headers=analyst, json={field: None})
        assert resp.status_code == 200 and resp.json()[field] == before

    def test_the_tier_filter_can_be_cleared(self, client, auth):
        analyst = auth("analyst")
        hook = create(client, analyst, tier_filter="HOT").json()
        resp = client.patch(f"/api/v1/webhooks/{hook['id']}", headers=analyst, json={"tier_filter": None})
        assert resp.json()["tier_filter"] is None

    def test_an_unknown_status_is_a_422(self, client, auth):
        analyst = auth("analyst")
        hook = create(client, analyst).json()
        assert (
            client.patch(f"/api/v1/webhooks/{hook['id']}", headers=analyst, json={"status": "exploded"}).status_code
            == 422
        )

    def test_an_unknown_webhook_is_a_404(self, client, auth):
        analyst = auth("analyst")
        missing = "00000000-0000-0000-0000-000000000000"
        assert client.patch(f"/api/v1/webhooks/{missing}", headers=analyst, json={"name": "x"}).status_code == 404
        assert client.get(f"/api/v1/webhooks/{missing}", headers=analyst).status_code == 404
        assert client.delete(f"/api/v1/webhooks/{missing}", headers=analyst).status_code == 404


class TestTestPing:
    def test_only_the_named_webhook_receives_the_ping(self, client, auth, monkeypatch):
        analyst = auth("analyst")
        target = create(client, analyst, url="https://one.example.com/h").json()
        create(
            client, analyst, url="https://two.example.com/h"
        )  # subscribed to the same events: it used to get the ping as well
        fake = FakeHttp()
        monkeypatch.setattr(webhook_service.httpx, "Client", fake)
        resp = client.post(
            f"/api/v1/webhooks/{target['id']}/test", headers=analyst, json={"event_type": "tier_crossed"}
        )
        assert (
            resp.status_code == 200 and resp.json()["delivered_to"] == 1 and resp.json()["delivery_status"] == "success"
        )
        assert [r["url"] for r in fake.requests] == ["https://one.example.com/h"]

    def test_the_ping_is_sent_even_if_the_webhook_is_paused_or_does_not_subscribe(self, client, auth, monkeypatch):
        analyst = auth("analyst")
        hook = create(client, analyst, events="conversion").json()
        client.patch(f"/api/v1/webhooks/{hook['id']}", headers=analyst, json={"status": "paused"})
        fake = FakeHttp()
        monkeypatch.setattr(webhook_service.httpx, "Client", fake)
        resp = client.post(f"/api/v1/webhooks/{hook['id']}/test", headers=analyst, json={"event_type": "tier_crossed"})
        assert resp.json()["delivered_to"] == 1 and len(fake.requests) == 1

    def test_the_request_is_signed_and_does_not_follow_redirects(self, client, auth, monkeypatch):
        import hashlib
        import hmac

        analyst = auth("analyst")
        hook = create(client, analyst, secret="signing-secret-0123456789").json()
        fake = FakeHttp()
        monkeypatch.setattr(webhook_service.httpx, "Client", fake)
        client.post(f"/api/v1/webhooks/{hook['id']}/test", headers=analyst, json={})
        request = fake.requests[0]
        expected = hmac.new(b"signing-secret-0123456789", request["content"], hashlib.sha256).hexdigest()
        assert request["headers"]["X-Revops-Signature"] == f"sha256={expected}"
        assert request["headers"]["X-Webhook-Event"] == "tier_crossed"
        assert fake.client_kwargs["follow_redirects"] is False and fake.client_kwargs["timeout"] == 15.0

    def test_a_failing_receiver_is_reported_not_raised(self, client, auth, monkeypatch, db):
        analyst = auth("analyst")
        hook = create(client, analyst).json()
        monkeypatch.setattr(webhook_service.httpx, "Client", FakeHttp(status=500, text="boom"))
        resp = client.post(f"/api/v1/webhooks/{hook['id']}/test", headers=analyst, json={})
        assert (
            resp.status_code == 200 and resp.json()["delivered_to"] == 0 and resp.json()["delivery_status"] == "failed"
        )
        log = db.get(WebhookDeliveryLog, resp.json()["delivery_id"])
        assert log.http_status_code == 500 and log.response_body == "boom"
        assert db.get(Webhook, hook["id"]).failed_deliveries == 1

    def test_a_connection_error_is_recorded(self, client, auth, monkeypatch, db):
        analyst = auth("analyst")
        hook = create(client, analyst).json()
        monkeypatch.setattr(webhook_service.httpx, "Client", FakeHttp(error=httpx.ConnectError("refused")))
        resp = client.post(f"/api/v1/webhooks/{hook['id']}/test", headers=analyst, json={})
        assert resp.json()["delivery_status"] == "failed"
        assert "refused" in db.get(WebhookDeliveryLog, resp.json()["delivery_id"]).error_message

    def test_a_target_that_now_points_inward_is_not_called(self, client, auth, monkeypatch, db):
        analyst = auth("analyst")
        hook = create(client, analyst).json()
        monkeypatch.setattr(
            "app.security.urls.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("169.254.169.254", 0))]
        )
        fake = FakeHttp()
        monkeypatch.setattr(webhook_service.httpx, "Client", fake)
        resp = client.post(f"/api/v1/webhooks/{hook['id']}/test", headers=analyst, json={})
        assert resp.json()["delivery_status"] == "failed" and fake.requests == []
        message = db.get(WebhookDeliveryLog, resp.json()["delivery_id"]).error_message
        assert "refused to call this URL" in message and "169.254.169.254" not in message

    def test_the_counters_and_last_trigger_are_updated(self, client, auth, monkeypatch, db):
        analyst = auth("analyst")
        hook = create(client, analyst).json()
        monkeypatch.setattr(webhook_service.httpx, "Client", FakeHttp())
        client.post(f"/api/v1/webhooks/{hook['id']}/test", headers=analyst, json={})
        row = db.get(Webhook, hook["id"])
        assert (row.total_deliveries, row.successful_deliveries, row.failed_deliveries) == (
            1,
            1,
            0,
        ) and row.last_triggered_at

    def test_an_unknown_webhook_is_a_404(self, client, auth):
        assert (
            client.post(
                "/api/v1/webhooks/00000000-0000-0000-0000-000000000000/test", headers=auth("analyst"), json={}
            ).status_code
            == 404
        )


class TestDeliveries:
    def test_deleting_a_webhook_removes_its_deliveries(self, client, auth, monkeypatch, db):
        analyst = auth("analyst")
        hook = create(client, analyst).json()
        monkeypatch.setattr(webhook_service.httpx, "Client", FakeHttp())
        client.post(f"/api/v1/webhooks/{hook['id']}/test", headers=analyst, json={})
        assert db.query(WebhookDeliveryLog).filter_by(webhook_id=hook["id"]).count() == 1
        assert client.delete(f"/api/v1/webhooks/{hook['id']}", headers=analyst).status_code == 204
        assert db.query(WebhookDeliveryLog).filter_by(webhook_id=hook["id"]).count() == 0

    def test_deliveries_are_listed_newest_first_with_paging_and_a_status_filter(self, client, auth, monkeypatch):
        analyst = auth("analyst")
        hook = create(client, analyst).json()
        for status in (200, 500, 200):
            monkeypatch.setattr(webhook_service.httpx, "Client", FakeHttp(status=status))
            client.post(f"/api/v1/webhooks/{hook['id']}/test", headers=analyst, json={})
        listing = client.get(f"/api/v1/webhooks/{hook['id']}/deliveries?page_size=2", headers=analyst).json()
        assert listing["total"] == 3 and listing["pages"] == 2 and len(listing["items"]) == 2
        failed = client.get(f"/api/v1/webhooks/{hook['id']}/deliveries?status=failed", headers=analyst).json()
        assert failed["total"] == 1 and failed["items"][0]["http_status_code"] == 500
        assert (
            client.get(f"/api/v1/webhooks/{hook['id']}/deliveries?page_size=1000", headers=analyst).status_code == 422
        )

    def test_a_failed_delivery_can_be_retried_once_it_is_fixed(self, client, auth, monkeypatch):
        analyst = auth("analyst")
        hook = create(client, analyst).json()
        monkeypatch.setattr(webhook_service.httpx, "Client", FakeHttp(status=500))
        delivery = client.post(f"/api/v1/webhooks/{hook['id']}/test", headers=analyst, json={}).json()["delivery_id"]
        monkeypatch.setattr(webhook_service.httpx, "Client", FakeHttp(status=200))
        assert (
            client.post(f"/api/v1/webhooks/{hook['id']}/deliveries/{delivery}/retry", headers=analyst).status_code
            == 200
        )
        assert (
            client.post(f"/api/v1/webhooks/{hook['id']}/deliveries/{delivery}/retry", headers=analyst).status_code
            == 409
        )  # now successful

    def test_a_delivery_of_another_webhook_cannot_be_retried_through_this_one(self, client, auth, monkeypatch):
        analyst = auth("analyst")
        one, two = create(client, analyst).json(), create(client, analyst).json()
        monkeypatch.setattr(webhook_service.httpx, "Client", FakeHttp(status=500))
        delivery = client.post(f"/api/v1/webhooks/{one['id']}/test", headers=analyst, json={}).json()["delivery_id"]
        assert (
            client.post(f"/api/v1/webhooks/{two['id']}/deliveries/{delivery}/retry", headers=analyst).status_code == 404
        )

    def test_retries_stop_at_the_maximum(self, client, auth, monkeypatch):
        analyst = auth("analyst")
        hook = create(client, analyst).json()
        monkeypatch.setattr(webhook_service.httpx, "Client", FakeHttp(status=500))
        delivery = client.post(f"/api/v1/webhooks/{hook['id']}/test", headers=analyst, json={}).json()["delivery_id"]
        codes = [
            client.post(f"/api/v1/webhooks/{hook['id']}/deliveries/{delivery}/retry", headers=analyst).status_code
            for _ in range(webhook_service.MAX_ATTEMPTS + 1)
        ]
        assert codes == [200] * (webhook_service.MAX_ATTEMPTS - 1) + [409, 409]
