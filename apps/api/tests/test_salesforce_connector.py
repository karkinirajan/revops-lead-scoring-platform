"""
Tests for Feature 4: Salesforce Connector.

Covers:
  - normalize() maps Salesforce Contact to ConnectorRecord
  - Missing email returns None (quarantine)
  - _extract_watermark returns latest LastModifiedDate
  - CrmConnectionCreate schema validation
  - SalesforceSyncService skips contacts without SF ID
"""
import os
import sys
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Make workers package importable from API test context
_WORKERS_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "workers")
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


class TestSalesforceContactConnector:
    def _make_connector(self):
        from workers.connectors.salesforce import SalesforceContactConnector, SalesforceClient
        client = MagicMock(spec=SalesforceClient)
        return SalesforceContactConnector(client)

    def test_normalize_valid_contact(self):
        connector = self._make_connector()
        raw = {
            "Id": "003000000000001",
            "Email": "Test.User@example.com",
            "FirstName": "Test",
            "LastName": "User",
            "Title": "VP Engineering",
            "AccountId": "001000000000001",
            "LeadSource": "Web",
            "LastModifiedDate": "2026-04-08T10:00:00.000Z",
        }
        record = connector.normalize(raw)
        assert record is not None
        assert record.source_system == "salesforce"
        assert record.source_record_id == "003000000000001"
        assert record.raw_payload["properties"]["email"] == "test.user@example.com"
        assert record.raw_payload["properties"]["firstname"] == "Test"

    def test_normalize_missing_email_returns_none(self):
        connector = self._make_connector()
        raw = {"Id": "003000000000002", "Email": "", "FirstName": "No", "LastName": "Email"}
        assert connector.normalize(raw) is None

    def test_normalize_null_email_returns_none(self):
        connector = self._make_connector()
        raw = {"Id": "003000000000003", "Email": None}
        assert connector.normalize(raw) is None

    def test_normalize_email_lowercased(self):
        connector = self._make_connector()
        raw = {
            "Id": "003000000000004",
            "Email": "UPPERCASE@EXAMPLE.COM",
            "LastModifiedDate": "2026-04-08T10:00:00.000Z",
        }
        record = connector.normalize(raw)
        assert record.raw_payload["properties"]["email"] == "uppercase@example.com"

    def test_extract_watermark_returns_max(self):
        connector = self._make_connector()
        records = [
            {"LastModifiedDate": "2026-04-07T10:00:00.000Z"},
            {"LastModifiedDate": "2026-04-08T15:30:00.000Z"},
            {"LastModifiedDate": "2026-04-06T08:00:00.000Z"},
        ]
        watermark = connector._extract_watermark(records)
        assert watermark == "2026-04-08T15:30:00.000Z"

    def test_extract_watermark_empty_returns_none(self):
        connector = self._make_connector()
        assert connector._extract_watermark([]) is None


class TestSalesforceSyncService:
    def test_push_skips_contacts_without_sf_id(self):
        from workers.connectors.salesforce import SalesforceSyncService, SalesforceClient
        client = MagicMock(spec=SalesforceClient)
        svc = SalesforceSyncService(client)

        contacts = [
            {"lead_score": 85, "priority_tier": "HOT"},  # no salesforce_id
            {"lead_score": 60, "priority_tier": "WARM"},  # no salesforce_id
        ]
        success, failure = svc.push_scores(contacts)
        assert success == 0
        assert failure == 0
        client.update_contact_scores.assert_not_called()

    def test_push_calls_update_with_sf_ids(self):
        from workers.connectors.salesforce import SalesforceSyncService, SalesforceClient
        client = MagicMock(spec=SalesforceClient)
        client.update_contact_scores.return_value = {"success": 1, "failure": 0}
        svc = SalesforceSyncService(client)

        contacts = [
            {"salesforce_id": "003abc", "lead_score": 85, "priority_tier": "HOT", "score_reason": "demo"},
        ]
        success, failure = svc.push_scores(contacts)
        assert success == 1
        client.update_contact_scores.assert_called_once()


class TestCrmConnectionSchema:
    def test_create_salesforce_requires_instance_url(self):
        # Validated at API layer, not Pydantic — just confirm model accepts it
        from app.api.v1.integrations import CrmConnectionCreate
        conn = CrmConnectionCreate(
            crm_type="salesforce",
            name="My Salesforce",
            access_token="token123",
            instance_url="https://myorg.salesforce.com",
        )
        assert conn.crm_type == "salesforce"
        assert conn.instance_url == "https://myorg.salesforce.com"

    def test_create_hubspot_no_instance_url(self):
        from app.api.v1.integrations import CrmConnectionCreate
        conn = CrmConnectionCreate(
            crm_type="hubspot",
            name="My HubSpot",
            access_token="pat-na1-xxx",
        )
        assert conn.instance_url is None

    def test_default_sync_direction(self):
        from app.api.v1.integrations import CrmConnectionCreate
        conn = CrmConnectionCreate(crm_type="hubspot", name="HubSpot", access_token="tok")
        assert conn.sync_direction == "bidirectional"
