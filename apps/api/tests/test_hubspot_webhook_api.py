import base64
import hashlib
import hmac
import json
import time

import pytest

from app.config import get_settings
from app.models.conversion import Conversion

SECRET = "hubspot-client-secret"
PATH = "/api/v1/analytics/conversions/hubspot"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(get_settings(), "hubspot_webhook_secret", SECRET)
    monkeypatch.setattr(get_settings(), "public_api_url", "")


def deal(email="ada@example.com", deal_id=4242, amount="1500"):
    return {"objectId": deal_id, "properties": {"email": {"value": email}, "amount": {"value": amount}}}


def signed(body, *, url="http://testserver" + PATH, timestamp=None, secret=SECRET, method="POST"):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    stamp = str(timestamp if timestamp is not None else int(time.time() * 1000))
    digest = hmac.new(secret.encode(), (method + url + raw.decode() + stamp).encode(), hashlib.sha256).digest()
    return raw, {
        "X-HubSpot-Signature-v3": base64.b64encode(digest).decode(),
        "X-HubSpot-Request-Timestamp": stamp,
        "Content-Type": "application/json",
    }


def post(client, body, **kwargs):
    raw, headers = signed(body, **kwargs)
    return client.post(PATH, content=raw, headers=headers)


class TestAuthentication:
    def test_without_a_configured_secret_the_endpoint_is_off(self, client, monkeypatch):
        monkeypatch.setattr(get_settings(), "hubspot_webhook_secret", "")
        resp = client.post(PATH, json=[deal()])
        assert resp.status_code == 503 and "HUBSPOT_WEBHOOK_SECRET" in resp.json()["detail"]

    def test_a_request_with_no_signature_is_refused(self, client, make_contact, db):
        make_contact(email="ada@example.com")
        resp = client.post(PATH, json=[deal()])  # this used to be accepted: no signature header meant no check
        assert resp.status_code == 401 and db.query(Conversion).count() == 0

    def test_a_request_with_only_a_signature_or_only_a_timestamp_is_refused(self, client):
        raw, headers = signed([deal()])
        assert (
            client.post(
                PATH, content=raw, headers={k: v for k, v in headers.items() if k != "X-HubSpot-Request-Timestamp"}
            ).status_code
            == 401
        )
        assert (
            client.post(
                PATH, content=raw, headers={k: v for k, v in headers.items() if k != "X-HubSpot-Signature-v3"}
            ).status_code
            == 401
        )

    def test_a_wrong_signature_is_refused(self, client, make_contact, db):
        make_contact(email="ada@example.com")
        assert post(client, [deal()], secret="not-the-secret").status_code == 401
        assert db.query(Conversion).count() == 0

    def test_a_body_changed_after_signing_is_refused(self, client):
        raw, headers = signed([deal(amount="10")])
        assert client.post(PATH, content=raw.replace(b"10", b"99"), headers=headers).status_code == 401

    def test_an_old_request_is_refused(self, client):
        assert post(client, [deal()], timestamp=int((time.time() - 301) * 1000)).status_code == 401

    def test_a_request_signed_for_another_url_is_refused(self, client):
        assert post(client, [deal()], url="http://testserver/api/v1/other").status_code == 401

    def test_the_signed_url_can_be_the_public_one_behind_a_proxy(self, client, monkeypatch, make_contact):
        make_contact(email="ada@example.com")
        monkeypatch.setattr(get_settings(), "public_api_url", "https://api.example.com/")
        assert post(client, [deal()]).status_code == 401  # signed for the internal URL
        assert post(client, [deal()], url="https://api.example.com" + PATH).status_code == 200

    def test_the_query_string_is_part_of_the_signed_url(self, client, make_contact):
        make_contact(email="ada@example.com")
        raw, headers = signed([deal()], url="http://testserver" + PATH + "?portal=1")
        assert client.post(PATH + "?portal=1", content=raw, headers=headers).status_code == 200
        assert client.post(PATH + "?portal=2", content=raw, headers=headers).status_code == 401

    def test_a_forged_request_creates_nothing(self, client, make_contact, db):
        make_contact(email="ada@example.com")
        for _ in range(3):
            client.post(PATH, json=[deal(deal_id=i) for i in range(5)])
        assert db.query(Conversion).count() == 0


class TestProcessing:
    def test_a_signed_deal_creates_a_conversion_with_the_score_at_the_time(self, client, make_contact, db):
        contact = make_contact(email="ada@example.com", score=88, tier="HOT")
        resp = post(client, [deal()])
        assert resp.status_code == 200 and resp.json() == {"status": "ok", "created": 1}
        conversion = db.query(Conversion).one()
        assert (conversion.contact_id, conversion.crm_deal_id, conversion.deal_value, conversion.source) == (
            contact.id,
            "4242",
            1500.0,
            "hubspot_webhook",
        )
        assert (conversion.score_at_conversion, conversion.tier_at_conversion) == (88, "HOT")

    def test_a_single_object_is_accepted_as_well_as_a_list(self, client, make_contact, db):
        make_contact(email="ada@example.com")
        assert post(client, deal()).json()["created"] == 1

    def test_the_same_deal_twice_creates_one_conversion(self, client, make_contact, db):
        make_contact(email="ada@example.com")
        assert post(client, [deal()]).json()["created"] == 1
        assert post(client, [deal()]).json()["created"] == 0
        assert db.query(Conversion).count() == 1

    def test_the_email_is_matched_ignoring_case_and_spaces_in_the_event(self, client, make_contact, db):
        make_contact(email="ada@example.com")
        assert post(client, [deal(email="  ada@example.com ")]).json()["created"] == 1

    def test_an_unknown_contact_is_skipped(self, client, db):
        assert post(client, [deal(email="nobody@example.com")]).json()["created"] == 0

    @pytest.mark.parametrize(
        "event",
        [
            "a string",
            42,
            None,
            [],
            {},
            {"objectId": 1},
            {"objectId": 1, "properties": "x"},
            {"objectId": 1, "properties": {"email": "ada@example.com"}},
            {"objectId": 1, "properties": {"email": {"value": 5}}},
            {"properties": {"email": {"value": "ada@example.com"}}},
        ],
    )
    def test_odd_events_are_skipped_without_failing_the_request(self, client, make_contact, event):
        make_contact(email="ada@example.com")
        resp = post(client, [event])
        assert resp.status_code == 200 and resp.json()["created"] == 0

    @pytest.mark.parametrize(
        ("amount", "expected"),
        [("1500.50", 1500.5), ("abc", None), ("nan", None), ("inf", None), ("", 0.0), (None, 0.0)],
    )
    def test_the_deal_value_is_read_defensively(self, client, make_contact, db, amount, expected):
        make_contact(email="ada@example.com")
        event = deal()
        event["properties"]["amount"] = {"value": amount}
        post(client, [event])
        assert db.query(Conversion).one().deal_value == expected

    def test_a_missing_amount_is_zero(self, client, make_contact, db):
        make_contact(email="ada@example.com")
        event = deal()
        del event["properties"]["amount"]
        post(client, [event])
        assert db.query(Conversion).one().deal_value == 0.0

    def test_invalid_json_is_a_400(self, client):
        assert post(client, b"{not json").status_code == 400

    def test_too_many_events_are_a_413(self, client):
        assert post(client, [deal(deal_id=i) for i in range(1001)]).status_code == 413

    def test_an_oversized_body_is_a_413(self, client):
        assert post(client, b"[" + b" " * 1_000_001 + b"]").status_code == 413

    def test_a_shadow_score_is_not_the_score_at_conversion(self, client, make_contact, db):
        make_contact(email="ada@example.com", score=50, tier="WARM")
        from app.models.scoring import LeadScore

        row = db.query(LeadScore).one()
        db.add(
            LeadScore(
                contact_id=row.contact_id, lead_score=99, priority_tier="HOT", model_version="2.x", is_shadow=True
            )
        )
        db.commit()
        post(client, [deal()])
        assert db.query(Conversion).one().score_at_conversion == 50
