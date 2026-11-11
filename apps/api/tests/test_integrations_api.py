import httpx
import pytest
from sqlalchemy import text

from app.auth.jwt import create_access_token
from app.config import get_settings
from app.models.crm_connection import CrmConnection

SF_URL = "https://acme.my.salesforce.com"


def sf_body(**override):
    return {
        "crm_type": "salesforce",
        "name": "Acme SF",
        "access_token": "sf-access",
        "refresh_token": "sf-refresh",
        "instance_url": SF_URL,
        **override,
    }


class TestPermissions:
    def test_only_admins_create_change_or_delete_connections(self, client, auth):
        for role in ("viewer", "analyst"):
            headers = auth(role)
            assert client.post("/api/v1/integrations", headers=headers, json=sf_body()).status_code == 403
        admin = auth("admin")
        conn = client.post("/api/v1/integrations", headers=admin, json=sf_body()).json()
        for role in ("viewer", "analyst"):
            headers = auth(role)
            assert (
                client.patch(f"/api/v1/integrations/{conn['id']}", headers=headers, json={"name": "x"}).status_code
                == 403
            )
            assert client.delete(f"/api/v1/integrations/{conn['id']}", headers=headers).status_code == 403

    def test_viewers_can_read_but_never_see_tokens(self, client, auth):
        admin = auth("admin")
        conn = client.post("/api/v1/integrations", headers=admin, json=sf_body()).json()
        viewer = auth("viewer")
        for response in (
            client.get("/api/v1/integrations", headers=viewer),
            client.get(f"/api/v1/integrations/{conn['id']}", headers=viewer),
            client.get(f"/api/v1/integrations/{conn['id']}/status", headers=viewer),
        ):
            assert response.status_code == 200
            assert (
                "sf-access" not in response.text
                and "sf-refresh" not in response.text
                and "token" not in response.text.replace("total", "")
            )

    def test_syncs_need_the_analyst_role(self, client, auth):
        admin = auth("admin")
        conn = client.post("/api/v1/integrations", headers=admin, json=sf_body()).json()
        assert client.post(f"/api/v1/integrations/{conn['id']}/sync-inbound", headers=auth("viewer")).status_code == 403
        assert (
            client.post(f"/api/v1/integrations/{conn['id']}/sync-outbound", headers=auth("viewer")).status_code == 403
        )

    def test_no_token_is_a_401(self, client):
        assert client.get("/api/v1/integrations").status_code == 401
        assert client.post("/api/v1/integrations/salesforce/oauth/callback?code=x&state=y").status_code == 401


class TestCreate:
    def test_a_salesforce_connection_is_created_with_encrypted_tokens(self, client, auth, db):
        resp = client.post("/api/v1/integrations", headers=auth("admin"), json=sf_body())
        assert resp.status_code == 201
        body = resp.json()
        assert (
            body["instance_url"] == SF_URL and body["sync_direction"] == "bidirectional" and body["is_active"] is True
        )
        raw = db.execute(
            text("SELECT access_token, refresh_token FROM crm_connections WHERE id = :i"), {"i": body["id"]}
        ).one()
        assert raw[0].startswith("enc:v1:") and raw[1].startswith("enc:v1:") and "sf-access" not in raw[0]
        assert db.get(CrmConnection, body["id"]).access_token == "sf-access"

    def test_a_hubspot_connection_needs_no_instance_url(self, client, auth):
        resp = client.post(
            "/api/v1/integrations",
            headers=auth("admin"),
            json={"crm_type": "hubspot", "name": "HubSpot", "access_token": "hs-token"},
        )
        assert resp.status_code == 201 and resp.json()["instance_url"] is None

    def test_a_hubspot_connection_with_an_instance_url_is_refused(self, client, auth):
        resp = client.post(
            "/api/v1/integrations",
            headers=auth("admin"),
            json={"crm_type": "hubspot", "name": "H", "access_token": "t", "instance_url": SF_URL},
        )
        assert resp.status_code == 400

    def test_salesforce_needs_an_instance_url(self, client, auth):
        body = sf_body()
        del body["instance_url"]
        assert client.post("/api/v1/integrations", headers=auth("admin"), json=body).status_code == 400

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.example.com",
            "http://acme.my.salesforce.com",
            "https://salesforce.com.evil.test",
            "https://127.0.0.1",
            "https://u:p@acme.my.salesforce.com",
            "https://acme.my.salesforce.com@evil.test",
        ],
    )
    def test_an_instance_url_that_is_not_salesforce_is_a_422(self, client, auth, url):
        resp = client.post("/api/v1/integrations", headers=auth("admin"), json=sf_body(instance_url=url))
        assert resp.status_code == 422 and "instance_url" in resp.text

    def test_a_trailing_slash_is_removed(self, client, auth):
        assert (
            client.post("/api/v1/integrations", headers=auth("admin"), json=sf_body(instance_url=SF_URL + "/")).json()[
                "instance_url"
            ]
            == SF_URL
        )

    @pytest.mark.parametrize(
        "override",
        [{"crm_type": "zoho"}, {"sync_direction": "sideways"}, {"name": ""}, {"access_token": ""}, {"name": "x" * 300}],
    )
    def test_invalid_values_are_a_422(self, client, auth, override):
        assert client.post("/api/v1/integrations", headers=auth("admin"), json=sf_body(**override)).status_code == 422


class TestUpdate:
    def _conn(self, client, admin):
        return client.post("/api/v1/integrations", headers=admin, json=sf_body()).json()

    def test_settings_can_be_changed_and_tokens_replaced(self, client, auth, db):
        admin = auth("admin")
        conn = self._conn(client, admin)
        resp = client.patch(
            f"/api/v1/integrations/{conn['id']}",
            headers=admin,
            json={"name": "Renamed", "is_active": False, "sync_direction": "outbound", "access_token": "new-token"},
        )
        assert resp.status_code == 200 and (
            resp.json()["name"],
            resp.json()["is_active"],
            resp.json()["sync_direction"],
        ) == ("Renamed", False, "outbound")
        db.expire_all()
        assert db.get(CrmConnection, conn["id"]).access_token == "new-token"

    @pytest.mark.parametrize("field", ["name", "is_active", "sync_direction", "access_token"])
    def test_required_settings_cannot_be_cleared(self, client, auth, db, field):
        admin = auth("admin")
        conn = self._conn(client, admin)
        before = client.get(f"/api/v1/integrations/{conn['id']}", headers=admin).json()
        resp = client.patch(f"/api/v1/integrations/{conn['id']}", headers=admin, json={field: None})
        assert resp.status_code == 200
        if field != "access_token":
            assert resp.json()[field] == before[field]
        db.expire_all()
        assert db.get(CrmConnection, conn["id"]).access_token == "sf-access"

    def test_the_instance_url_cannot_be_changed_after_creation(self, client, auth):
        admin = auth("admin")
        conn = self._conn(client, admin)
        client.patch(
            f"/api/v1/integrations/{conn['id']}", headers=admin, json={"instance_url": "https://evil.example.com"}
        )
        assert client.get(f"/api/v1/integrations/{conn['id']}", headers=admin).json()["instance_url"] == SF_URL

    def test_unknown_connections_are_a_404(self, client, auth):
        admin, missing = auth("admin"), "00000000-0000-0000-0000-000000000000"
        assert client.get(f"/api/v1/integrations/{missing}", headers=admin).status_code == 404
        assert client.patch(f"/api/v1/integrations/{missing}", headers=admin, json={}).status_code == 404
        assert client.delete(f"/api/v1/integrations/{missing}", headers=admin).status_code == 404

    def test_a_connection_can_be_deleted(self, client, auth):
        admin = auth("admin")
        conn = self._conn(client, admin)
        assert client.delete(f"/api/v1/integrations/{conn['id']}", headers=admin).status_code == 204
        assert client.get(f"/api/v1/integrations/{conn['id']}", headers=admin).status_code == 404


class FakeSalesforce:
    """Replaces SalesforceClient: records the Salesforce ids that scores are pushed to."""

    pushed: list[dict] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def update_contact_scores(self, contacts):
        FakeSalesforce.pushed = contacts
        return {"success": len(contacts), "failure": 0}


class TestSyncOutbound:
    def test_scores_go_to_the_salesforce_id_of_salesforce_contacts_only(self, client, auth, make_contact, monkeypatch):
        make_contact(
            email="from-sf@example.com",
            source_system="salesforce",
            source_record_id="003SFID0001",
            hubspot_contact_id="9001",
            score=90,
            tier="HOT",
        )
        make_contact(
            email="from-hs@example.com",
            source_system="hubspot",
            source_record_id="9002",
            hubspot_contact_id="9002",
            score=85,
            tier="HOT",
        )
        make_contact(
            email="cold@example.com", source_system="salesforce", source_record_id="003SFID0003", score=10, tier="COLD"
        )
        monkeypatch.setattr("workers.connectors.salesforce.SalesforceClient", FakeSalesforce)
        admin = auth("admin")
        conn = client.post("/api/v1/integrations", headers=admin, json=sf_body()).json()
        FakeSalesforce.pushed = []
        resp = client.post(f"/api/v1/integrations/{conn['id']}/sync-outbound", headers=admin)
        assert resp.status_code == 200
        assert [c["id"] for c in FakeSalesforce.pushed] == [
            "003SFID0001"
        ]  # not the HubSpot id, not the HubSpot-only contact, not the COLD one
        assert (
            resp.json()["success"] == 1
            and resp.json()["records_processed"] == 1
            and resp.json()["direction"] == "outbound"
        )

    def test_the_connections_counters_are_updated(self, client, auth, make_contact, monkeypatch, db):
        make_contact(source_system="salesforce", source_record_id="003A", score=95, tier="HOT")
        monkeypatch.setattr("workers.connectors.salesforce.SalesforceClient", FakeSalesforce)
        admin = auth("admin")
        conn = client.post("/api/v1/integrations", headers=admin, json=sf_body()).json()
        client.post(f"/api/v1/integrations/{conn['id']}/sync-outbound", headers=admin)
        row = db.get(CrmConnection, conn["id"])
        assert row.total_records_synced == 1 and row.last_outbound_sync_at is not None

    def test_shadow_scores_are_not_pushed(self, client, auth, make_contact, monkeypatch):
        make_contact(source_system="salesforce", source_record_id="003S", score=99, tier="HOT", shadow=True)
        monkeypatch.setattr("workers.connectors.salesforce.SalesforceClient", FakeSalesforce)
        admin = auth("admin")
        conn = client.post("/api/v1/integrations", headers=admin, json=sf_body()).json()
        FakeSalesforce.pushed = []
        resp = client.post(f"/api/v1/integrations/{conn['id']}/sync-outbound", headers=admin)
        assert FakeSalesforce.pushed == [] and resp.json()["records_processed"] == 0

    def test_a_disabled_connection_is_not_synced(self, client, auth):
        admin = auth("admin")
        conn = client.post("/api/v1/integrations", headers=admin, json=sf_body()).json()
        client.patch(f"/api/v1/integrations/{conn['id']}", headers=admin, json={"is_active": False})
        assert client.post(f"/api/v1/integrations/{conn['id']}/sync-outbound", headers=admin).status_code == 409
        assert client.post(f"/api/v1/integrations/{conn['id']}/sync-inbound", headers=admin).status_code == 409

    def test_a_connection_whose_url_is_not_salesforce_is_refused_not_called(self, client, auth, db):
        admin = auth("admin")
        conn = client.post("/api/v1/integrations", headers=admin, json=sf_body()).json()
        db.execute(
            text("UPDATE crm_connections SET instance_url = 'https://evil.example.com' WHERE id = :i"),
            {"i": conn["id"]},
        )
        db.commit()
        resp = client.post(f"/api/v1/integrations/{conn['id']}/sync-outbound", headers=admin)
        assert resp.status_code == 409 and "not usable" in resp.json()["detail"]


class TestSyncInbound:
    def test_a_salesforce_pull_runs_the_connector_and_reports_what_it_published(self, client, auth, monkeypatch, db):
        class FakeConnector:
            def __init__(self, client):
                self.client = client

            def run(self):
                return {"published": 7, "skipped": 2, "watermark": "2026-01-01T00:00:00Z"}

        monkeypatch.setattr("workers.connectors.salesforce.SalesforceClient", FakeSalesforce)
        monkeypatch.setattr("workers.connectors.salesforce.SalesforceContactConnector", FakeConnector)
        admin = auth("admin")
        conn = client.post("/api/v1/integrations", headers=admin, json=sf_body()).json()
        resp = client.post(f"/api/v1/integrations/{conn['id']}/sync-inbound", headers=admin).json()
        assert (resp["records_processed"], resp["success"], resp["failure"], resp["direction"]) == (9, 7, 0, "inbound")
        assert db.get(CrmConnection, conn["id"]).last_inbound_sync_at is not None

    def test_a_failure_is_recorded_not_raised(self, client, auth, monkeypatch, db):
        class Broken:
            def __init__(self, client):
                pass

            def run(self):
                raise RuntimeError("salesforce said no")

        monkeypatch.setattr("workers.connectors.salesforce.SalesforceClient", FakeSalesforce)
        monkeypatch.setattr("workers.connectors.salesforce.SalesforceContactConnector", Broken)
        admin = auth("admin")
        conn = client.post("/api/v1/integrations", headers=admin, json=sf_body()).json()
        resp = client.post(f"/api/v1/integrations/{conn['id']}/sync-inbound", headers=admin).json()
        assert resp["failure"] == 1 and resp["success"] == 0
        assert (
            "salesforce said no"
            in client.get(f"/api/v1/integrations/{conn['id']}/status", headers=admin).json()["last_sync_error"]
        )

    def test_a_hubspot_pull_runs_its_connector_with_the_connections_credentials(self, client, auth, monkeypatch):
        seen = {}

        class FakeHubSpot:
            def __init__(self, access_token, portal_id=""):
                seen.update(access_token=access_token, portal_id=portal_id)

            def run(self):
                return {"published": 3, "skipped": 1, "watermark": None}

        monkeypatch.setattr("workers.connectors.hubspot.HubSpotConnector", FakeHubSpot)
        admin = auth("admin")
        conn = client.post(
            "/api/v1/integrations",
            headers=admin,
            json={"crm_type": "hubspot", "name": "H", "access_token": "hs-token", "org_id": "12345"},
        ).json()
        resp = client.post(f"/api/v1/integrations/{conn['id']}/sync-inbound", headers=admin).json()
        assert seen == {"access_token": "hs-token", "portal_id": "12345"}
        assert (resp["records_processed"], resp["success"], resp["failure"]) == (4, 3, 0)


@pytest.fixture()
def oauth_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "salesforce_client_id", "client-id")
    monkeypatch.setattr(settings, "salesforce_client_secret", "client-secret")
    monkeypatch.setattr(settings, "salesforce_redirect_uri", "https://app.example.com/oauth/callback")
    return settings


class TestSalesforceOAuth:
    def test_it_is_off_until_configured(self, client, auth):
        admin = auth("admin")
        assert client.get("/api/v1/integrations/salesforce/oauth/authorize", headers=admin).status_code == 503
        assert (
            client.post("/api/v1/integrations/salesforce/oauth/callback?code=c&state=s", headers=admin).status_code
            == 503
        )

    def test_authorize_returns_a_consent_url_with_a_signed_state(self, client, auth, oauth_settings):
        from urllib.parse import parse_qs, urlsplit

        resp = client.get("/api/v1/integrations/salesforce/oauth/authorize", headers=auth("admin"))
        assert resp.status_code == 200
        url = urlsplit(resp.json()["authorize_url"])
        query = parse_qs(url.query)
        assert (url.scheme, url.netloc, url.path) == ("https", "login.salesforce.com", "/services/oauth2/authorize")
        assert (
            query["response_type"] == ["code"]
            and query["client_id"] == ["client-id"]
            and query["redirect_uri"] == ["https://app.example.com/oauth/callback"]
        )
        assert "client-secret" not in resp.text and len(query["state"][0]) > 50

    def test_only_admins_can_start_it(self, client, auth, oauth_settings):
        assert client.get("/api/v1/integrations/salesforce/oauth/authorize", headers=auth("analyst")).status_code == 403

    def _exchange(self, monkeypatch, response):
        calls = []

        def fake_post(url, **kwargs):
            calls.append({"url": url, **kwargs})
            return response

        monkeypatch.setattr("app.api.v1.integrations.httpx.post", fake_post)
        return calls

    def _token_response(self, **override):
        data = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "instance_url": SF_URL,
            "id": "https://login.salesforce.com/id/00Dxx0000001gER/005xx000001Sv6A",
            **override,
        }
        return httpx.Response(
            200, json=data, request=httpx.Request("POST", "https://login.salesforce.com/services/oauth2/token")
        )

    def _state(self, client, headers):
        from urllib.parse import parse_qs, urlsplit

        url = client.get("/api/v1/integrations/salesforce/oauth/authorize", headers=headers).json()["authorize_url"]
        return parse_qs(urlsplit(url).query)["state"][0]

    def test_the_callback_exchanges_the_code_and_stores_encrypted_tokens(
        self, client, auth, oauth_settings, monkeypatch, db
    ):
        admin = auth("admin")
        state = self._state(client, admin)
        calls = self._exchange(monkeypatch, self._token_response())
        resp = client.post(f"/api/v1/integrations/salesforce/oauth/callback?code=the-code&state={state}", headers=admin)
        assert resp.status_code == 201 and resp.json()["instance_url"] == SF_URL
        assert (
            calls[0]["url"] == "https://login.salesforce.com/services/oauth2/token"
            and calls[0]["follow_redirects"] is False
        )
        assert (
            calls[0]["data"]["code"] == "the-code"
            and calls[0]["data"]["client_secret"] == "client-secret"
            and calls[0]["data"]["grant_type"] == "authorization_code"
        )
        row = db.get(CrmConnection, resp.json()["connection_id"])
        assert (row.access_token, row.refresh_token, row.org_id, row.crm_type) == (
            "new-access",
            "new-refresh",
            "00Dxx0000001gER",
            "salesforce",
        )
        assert (
            db.execute(text("SELECT access_token FROM crm_connections WHERE id = :i"), {"i": row.id})
            .scalar()
            .startswith("enc:v1:")
        )

    def test_a_callback_without_a_state_is_refused(self, client, auth, oauth_settings):
        assert (
            client.post("/api/v1/integrations/salesforce/oauth/callback?code=c", headers=auth("admin")).status_code
            == 422
        )

    @pytest.mark.parametrize("state", ["garbage", "a.b.c"])
    def test_a_forged_state_is_refused_before_anything_is_exchanged(
        self, client, auth, oauth_settings, monkeypatch, state
    ):
        calls = self._exchange(monkeypatch, self._token_response())
        resp = client.post(
            f"/api/v1/integrations/salesforce/oauth/callback?code=c&state={state}", headers=auth("admin")
        )
        assert resp.status_code == 400 and calls == []

    def test_an_access_token_is_not_a_state(self, client, bearer, oauth_settings, monkeypatch, make_user):
        user = make_user(email="boss@example.com", role="admin")
        headers = bearer(user)
        calls = self._exchange(monkeypatch, self._token_response())
        resp = client.post(
            f"/api/v1/integrations/salesforce/oauth/callback?code=c&state={create_access_token(user.id)}",
            headers=headers,
        )
        assert resp.status_code == 400 and calls == []

    def test_a_state_given_to_one_admin_does_not_work_for_another(self, client, auth, oauth_settings, monkeypatch):
        state = self._state(client, auth("admin", email="one@example.com"))
        calls = self._exchange(monkeypatch, self._token_response())
        resp = client.post(
            f"/api/v1/integrations/salesforce/oauth/callback?code=c&state={state}",
            headers=auth("admin", email="two@example.com"),
        )
        assert resp.status_code == 400 and calls == []

    def test_the_callback_needs_a_logged_in_admin(self, client, auth, oauth_settings):
        state = self._state(client, auth("admin"))
        assert client.post(f"/api/v1/integrations/salesforce/oauth/callback?code=c&state={state}").status_code == 401
        assert (
            client.post(
                f"/api/v1/integrations/salesforce/oauth/callback?code=c&state={state}", headers=auth("analyst")
            ).status_code
            == 403
        )

    def test_salesforce_rejecting_the_code_is_a_400_without_its_text(self, client, auth, oauth_settings, monkeypatch):
        admin = auth("admin")
        state = self._state(client, admin)
        self._exchange(
            monkeypatch,
            httpx.Response(400, text="invalid_grant: secret detail", request=httpx.Request("POST", "https://x")),
        )
        resp = client.post(f"/api/v1/integrations/salesforce/oauth/callback?code=c&state={state}", headers=admin)
        assert resp.status_code == 400 and "secret detail" not in resp.text

    def test_an_instance_url_that_is_not_salesforce_in_the_answer_is_refused(
        self, client, auth, oauth_settings, monkeypatch, db
    ):
        admin = auth("admin")
        state = self._state(client, admin)
        self._exchange(monkeypatch, self._token_response(instance_url="https://evil.example.com"))
        resp = client.post(f"/api/v1/integrations/salesforce/oauth/callback?code=c&state={state}", headers=admin)
        assert resp.status_code == 502 and db.query(CrmConnection).count() == 0

    def test_a_login_url_that_is_not_salesforce_disables_the_flow(self, client, auth, oauth_settings, monkeypatch):
        monkeypatch.setattr(oauth_settings, "salesforce_login_url", "https://login.evil.example.com")
        assert client.get("/api/v1/integrations/salesforce/oauth/authorize", headers=auth("admin")).status_code == 503

    def test_the_sandbox_login_url_works(self, client, auth, oauth_settings, monkeypatch):
        monkeypatch.setattr(oauth_settings, "salesforce_login_url", "https://test.salesforce.com/")
        url = client.get("/api/v1/integrations/salesforce/oauth/authorize", headers=auth("admin")).json()[
            "authorize_url"
        ]
        assert url.startswith("https://test.salesforce.com/services/oauth2/authorize?")
