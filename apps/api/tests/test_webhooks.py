"""
Tests for Feature 3: Webhook Delivery Engine.

Covers:
  - Webhook model event_list / tier_filter_list parsing
  - WebhookCreate schema validation
  - Payload building and HMAC signing
  - _deliver_sync with mocked httpx
  - retry_failed_delivery max-attempts guard
"""

import json
from unittest.mock import MagicMock, patch

import pytest


class TestWebhookModel:
    def test_event_list_parsing(self):
        from app.models.webhook import Webhook

        wh = Webhook()
        wh.events = "tier_crossed,hot_lead,conversion"
        assert wh.event_list == ["tier_crossed", "hot_lead", "conversion"]

    def test_event_list_single(self):
        from app.models.webhook import Webhook

        wh = Webhook()
        wh.events = "score_updated"
        assert wh.event_list == ["score_updated"]

    def test_tier_filter_list_empty(self):
        from app.models.webhook import Webhook

        wh = Webhook()
        wh.tier_filter = None
        assert wh.tier_filter_list == []

    def test_tier_filter_list_parsed(self):
        from app.models.webhook import Webhook

        wh = Webhook()
        wh.tier_filter = "HOT,WARM"
        assert wh.tier_filter_list == ["HOT", "WARM"]

    def test_tier_filter_lowercased_to_upper(self):
        from app.models.webhook import Webhook

        wh = Webhook()
        wh.tier_filter = "hot,warm"
        assert wh.tier_filter_list == ["HOT", "WARM"]


class TestWebhookSchema:
    def test_valid_events(self):
        from app.schemas.webhook import WebhookCreate

        wc = WebhookCreate(
            name="Test",
            url="https://example.com/hook",
            events="tier_crossed,hot_lead",
        )
        assert "tier_crossed" in wc.events

    def test_invalid_event_raises(self):
        from pydantic import ValidationError

        from app.schemas.webhook import WebhookCreate

        with pytest.raises(ValidationError):
            WebhookCreate(name="Test", url="https://example.com/hook", events="invalid_event")

    def test_secret_not_in_read_schema(self):
        from app.schemas.webhook import WebhookRead

        fields = set(WebhookRead.model_fields.keys())
        assert "secret" not in fields


class TestWebhookPayload:
    def test_build_payload_structure(self):
        from app.services.webhook_service import build_payload

        p = build_payload("tier_crossed", "contact-123", {"score": 85, "tier": "HOT"})
        assert p["event"] == "tier_crossed"
        assert p["contact_id"] == "contact-123"
        assert p["data"]["score"] == 85
        assert "id" in p
        assert "timestamp" in p

    def test_payload_is_json_serializable(self):
        from app.services.webhook_service import build_payload

        p = build_payload("hot_lead", None, {"reason": "demo requested"})
        serialized = json.dumps(p)
        assert "hot_lead" in serialized

    def test_hmac_signing(self):
        import hashlib
        import hmac

        secret = "test-secret-key"
        payload_bytes = b'{"event": "tier_crossed"}'
        expected = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()

        from app.services.webhook_service import _sign_payload

        result = _sign_payload(secret, payload_bytes)
        assert result == expected


class TestDeliverSync:
    def test_successful_delivery(self):
        from app.models.webhook import Webhook, WebhookDeliveryLog, WebhookDeliveryStatus
        from app.services.webhook_service import _deliver_sync

        hook = Webhook()
        hook.id = "wh-1"
        hook.url = "https://example.com/hook"
        hook.secret = None
        hook.successful_deliveries = 0
        hook.failed_deliveries = 0

        log = WebhookDeliveryLog()
        log.id = "log-1"
        log.event_type = "tier_crossed"
        log.status = WebhookDeliveryStatus.PENDING

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.is_success = True
        mock_resp.text = "ok"

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            _deliver_sync(hook, log, b'{"event":"tier_crossed"}')

        assert log.status == WebhookDeliveryStatus.SUCCESS
        assert hook.successful_deliveries == 1

    def test_failed_delivery_4xx(self):
        from app.models.webhook import Webhook, WebhookDeliveryLog, WebhookDeliveryStatus
        from app.services.webhook_service import _deliver_sync

        hook = Webhook()
        hook.id = "wh-2"
        hook.url = "https://example.com/hook"
        hook.secret = None
        hook.successful_deliveries = 0
        hook.failed_deliveries = 0

        log = WebhookDeliveryLog()
        log.id = "log-2"
        log.event_type = "tier_crossed"
        log.status = WebhookDeliveryStatus.PENDING

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.is_success = False
        mock_resp.text = "Not found"

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            _deliver_sync(hook, log, b"{}")

        assert log.status == WebhookDeliveryStatus.FAILED
        assert hook.failed_deliveries == 1

    def test_network_error(self):
        from app.models.webhook import Webhook, WebhookDeliveryLog, WebhookDeliveryStatus
        from app.services.webhook_service import _deliver_sync

        hook = Webhook()
        hook.id = "wh-3"
        hook.url = "https://example.com/hook"
        hook.secret = None
        hook.successful_deliveries = 0
        hook.failed_deliveries = 0

        log = WebhookDeliveryLog()
        log.id = "log-3"
        log.event_type = "tier_crossed"
        log.status = WebhookDeliveryStatus.PENDING

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.side_effect = ConnectionError("refused")
            _deliver_sync(hook, log, b"{}")

        assert log.status == WebhookDeliveryStatus.FAILED
        assert "refused" in log.error_message


class TestRetryGuard:
    def test_max_attempts_returns_false(self):
        from app.models.webhook import WebhookDeliveryLog, WebhookDeliveryStatus
        from app.services.webhook_service import MAX_ATTEMPTS

        log = WebhookDeliveryLog()
        log.attempt_number = MAX_ATTEMPTS  # already at max
        log.status = WebhookDeliveryStatus.FAILED

        mock_db = MagicMock()
        mock_db.get.return_value = log

        from app.services.webhook_service import retry_failed_delivery

        result = retry_failed_delivery(mock_db, "log-999")
        assert result is False

    def test_already_successful_returns_false(self):
        from app.models.webhook import WebhookDeliveryLog, WebhookDeliveryStatus
        from app.services.webhook_service import retry_failed_delivery

        log = WebhookDeliveryLog()
        log.attempt_number = 1
        log.status = WebhookDeliveryStatus.SUCCESS

        mock_db = MagicMock()
        mock_db.get.return_value = log

        result = retry_failed_delivery(mock_db, "log-success")
        assert result is False
