import base64
import hashlib
import hmac

import pytest

from app.security.hubspot import MAX_AGE_MS, signed_url, verify_v3

SECRET = "app-client-secret"
URL = "https://api.example.com/api/v1/analytics/conversions/hubspot"
BODY = b'[{"objectId": 42, "properties": {"email": {"value": "ada@example.com"}}}]'
NOW = 1_752_613_922_216


def sign(*, method="POST", url=URL, body=BODY, timestamp=NOW, secret=SECRET):
    """HubSpot's documented construction, written out independently of the module under test."""
    message = f"{method}{url}{body.decode()}{timestamp}".encode()
    return base64.b64encode(hmac.new(secret.encode(), message, hashlib.sha256).digest()).decode()


def check(**override):
    args = {
        "secret": SECRET,
        "method": "POST",
        "url": URL,
        "body": BODY,
        "timestamp": str(NOW),
        "signature": sign(),
        "now_ms": NOW,
    }
    args.update(override)
    return verify_v3(**args)


class TestSignedUrl:
    def test_a_url_without_a_query_is_unchanged(self):
        assert signed_url(URL) == URL

    def test_the_listed_escapes_in_the_query_are_decoded(self):
        assert (
            signed_url("https://x.test/p?a=%3A%2F%3F%40%21%24%27%28%29%2A%2C%3B") == "https://x.test/p?a=:/?@!$'()*,;"
        )

    def test_lowercase_escapes_are_decoded_too(self):
        assert signed_url("https://x.test/p?a=%3a%2f") == "https://x.test/p?a=:/"

    def test_other_escapes_are_left_alone(self):
        assert signed_url("https://x.test/p?a=%20%25%26") == "https://x.test/p?a=%20%25%26"

    def test_the_path_is_not_decoded(self):
        assert signed_url("https://x.test/a%2Fb?c=%2F") == "https://x.test/a%2Fb?c=/"

    def test_the_fragment_is_dropped(self):
        assert signed_url("https://x.test/p?a=1#frag") == "https://x.test/p?a=1"
        assert signed_url("https://x.test/p#frag") == "https://x.test/p"


class TestVerify:
    def test_a_correctly_signed_request_is_accepted(self):
        assert check()

    def test_the_signature_matches_a_published_vector(self):
        # the example in HubSpot's documentation (Java validator): secret, URI, body, timestamp and signature as published
        secret = "cfc68c0b-4b4e-4ef8-b764-95350e4ea479"
        url = "https://webhook.site/335453f5-94b3-49d9-b684-a55354d4b8df"
        body = (
            '[{"eventId":531833541,"subscriptionId":3923621,"portalId":48807704,"appId":16111050,"occurredAt":1752613920733,'
            '"subscriptionType":"contact.creation","attemptNumber":0,"objectId":138017612137,"changeFlag":"CREATED",'
            '"changeSource":"CRM_UI","sourceId":"userId:76023669"}]'
        )
        assert verify_v3(
            secret=secret,
            method="POST",
            url=url,
            body=body.encode(),
            timestamp="1752613922216",
            signature="gbj1XPRvUt0noT7i7fXfTzOD4sLzQmf0VT28ZYq0EYg=",
            now_ms=1_752_613_922_216 + 1000,
        )

    @pytest.mark.parametrize(
        "override",
        [
            {"secret": "another-secret"},
            {"method": "GET"},
            {"url": "https://api.example.com/other"},
            {"body": BODY + b" "},
            {"timestamp": str(NOW + 1)},
            {"signature": "A" * 44},
            {"signature": "not base64 at all"},
        ],
    )
    def test_any_change_to_what_was_signed_is_rejected(self, override):
        assert not check(**override)

    @pytest.mark.parametrize("override", [{"secret": ""}, {"signature": ""}, {"timestamp": ""}])
    def test_missing_pieces_are_rejected(self, override):
        assert not check(**override)

    def test_no_secret_means_no_valid_signature_even_one_made_with_an_empty_key(self):
        assert not check(secret="", signature=sign(secret=""))

    def test_the_method_is_case_insensitive(self):
        assert check(method="post")

    def test_a_request_just_inside_the_window_is_accepted(self):
        assert check(now_ms=NOW + MAX_AGE_MS)

    def test_an_old_request_is_rejected(self):
        assert not check(now_ms=NOW + MAX_AGE_MS + 1)

    def test_a_request_from_the_future_is_rejected(self):
        assert not check(now_ms=NOW - MAX_AGE_MS - 1)
        assert check(now_ms=NOW - MAX_AGE_MS)

    @pytest.mark.parametrize("timestamp", ["abc", "1.5", "12 34"])
    def test_a_timestamp_that_is_not_an_integer_is_rejected(self, timestamp):
        assert not check(timestamp=timestamp, signature=sign(timestamp=timestamp))

    def test_a_body_that_is_not_utf8_is_rejected(self):
        assert not check(body=b"\xff\xfe", signature="x")

    def test_the_clock_is_used_when_no_time_is_given(self):
        import time

        now = int(time.time() * 1000)
        assert verify_v3(
            secret=SECRET, method="POST", url=URL, body=BODY, timestamp=str(now), signature=sign(timestamp=now)
        )
        assert not verify_v3(secret=SECRET, method="POST", url=URL, body=BODY, timestamp=str(NOW), signature=sign())

    def test_a_decoded_query_is_what_is_signed(self):
        url = "https://api.example.com/hook?q=%3A"
        assert check(url=url, signature=sign(url="https://api.example.com/hook?q=:"))
        assert not check(url=url, signature=sign(url=url))
