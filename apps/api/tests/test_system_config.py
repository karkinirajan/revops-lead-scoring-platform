"""GET /system/config: what the settings page may show about the deployment."""

import pytest

from app.config import get_settings

SECRETS = {
    "hubspot_access_token": "pat-na1-hubspot-token-value",
    "hubspot_portal_id": "12345678",
    "hubspot_webhook_secret": "hubspot-client-secret-value",
    "anthropic_api_key": "sk-ant-api-key-value",
}


@pytest.fixture()
def configured(monkeypatch):
    for name, value in SECRETS.items():
        monkeypatch.setattr(get_settings(), name, value)


@pytest.fixture()
def unconfigured(monkeypatch):
    for name in SECRETS:
        monkeypatch.setattr(get_settings(), name, "")


class TestSystemConfig:
    def test_it_needs_a_login(self, client):
        assert client.get("/api/v1/system/config").status_code == 401

    @pytest.mark.parametrize("role", ["viewer", "analyst", "admin"])
    def test_every_role_can_read_it(self, client, auth, role):
        assert client.get("/api/v1/system/config", headers=auth(role)).status_code == 200

    def test_it_says_which_secrets_are_set(self, client, auth, configured):
        body = client.get("/api/v1/system/config", headers=auth()).json()
        assert (
            body["hubspot_access_token_set"] is True
            and body["hubspot_portal_id_set"] is True
            and body["hubspot_webhook_secret_set"] is True
            and body["anthropic_api_key_set"] is True
        )

    def test_it_says_which_secrets_are_not(self, client, auth, unconfigured):
        body = client.get("/api/v1/system/config", headers=auth()).json()
        assert (
            body["hubspot_access_token_set"] is False
            and body["hubspot_portal_id_set"] is False
            and body["hubspot_webhook_secret_set"] is False
            and body["anthropic_api_key_set"] is False
        )

    @pytest.mark.parametrize(
        ("setting", "flag"),
        [
            ("hubspot_access_token", "hubspot_access_token_set"),
            ("hubspot_portal_id", "hubspot_portal_id_set"),
            ("hubspot_webhook_secret", "hubspot_webhook_secret_set"),
            ("anthropic_api_key", "anthropic_api_key_set"),
        ],
    )
    def test_each_secret_is_reported_on_its_own(self, client, auth, unconfigured, monkeypatch, setting, flag):
        monkeypatch.setattr(get_settings(), setting, "a-value-that-is-set")
        body = client.get("/api/v1/system/config", headers=auth()).json()
        flags = (
            "hubspot_access_token_set",
            "hubspot_portal_id_set",
            "hubspot_webhook_secret_set",
            "anthropic_api_key_set",
        )
        assert {name for name in flags if body[name]} == {flag}

    def test_the_secrets_themselves_are_never_sent(self, client, auth, configured):
        response = client.get("/api/v1/system/config", headers=auth())
        for value in SECRETS.values():
            assert value not in response.text
        assert set(response.json()) == {
            "hubspot_access_token_set",
            "hubspot_portal_id_set",
            "hubspot_webhook_secret_set",
            "hubspot_batch_size",
            "hubspot_rate_limit_per_second",
            "anthropic_api_key_set",
            "ai_model",
            "ai_cache_ttl_seconds",
            "ai_rate_limit_per_minute",
            "scoring_hot_threshold",
            "scoring_warm_threshold",
            "scoring_cool_threshold",
        }

    def test_it_reports_the_values_the_server_is_using(self, client, auth, monkeypatch):
        s = get_settings()
        monkeypatch.setattr(s, "ai_model", "claude-haiku-5-5")
        monkeypatch.setattr(s, "hubspot_batch_size", 25)
        monkeypatch.setattr(s, "hubspot_rate_limit_per_second", 4)
        monkeypatch.setattr(s, "ai_intelligence_cache_ttl_seconds", 600)
        monkeypatch.setattr(s, "ai_intelligence_rate_limit_per_minute", 3)
        monkeypatch.setattr(s, "scoring_hot_threshold", 90)
        monkeypatch.setattr(s, "scoring_warm_threshold", 60)
        monkeypatch.setattr(s, "scoring_cool_threshold", 30)
        assert client.get("/api/v1/system/config", headers=auth()).json() == {
            "hubspot_access_token_set": bool(s.hubspot_access_token),
            "hubspot_portal_id_set": bool(s.hubspot_portal_id),
            "hubspot_webhook_secret_set": bool(s.hubspot_webhook_secret),
            "hubspot_batch_size": 25,
            "hubspot_rate_limit_per_second": 4,
            "anthropic_api_key_set": bool(s.anthropic_api_key),
            "ai_model": "claude-haiku-5-5",
            "ai_cache_ttl_seconds": 600,
            "ai_rate_limit_per_minute": 3,
            "scoring_hot_threshold": 90,
            "scoring_warm_threshold": 60,
            "scoring_cool_threshold": 30,
        }
