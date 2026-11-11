"""Verifying that a webhook request really comes from HubSpot (the v3 request signature).

HubSpot signs `METHOD + URL + raw body + timestamp` with HMAC-SHA256 under the app's client secret, Base64-encodes it and sends it in `X-HubSpot-Signature-v3`
with the time in milliseconds in `X-HubSpot-Request-Timestamp`. A request older than five minutes is rejected, which limits replays. The URL is the public one
HubSpot called (with a few percent-escapes in the query string decoded, as HubSpot documents), which behind a proxy is not the one the app sees: see
`PUBLIC_API_URL`.
"""

import base64
import hashlib
import hmac
import time

MAX_AGE_MS = 5 * 60 * 1000
SIGNATURE_HEADER = "x-hubspot-signature-v3"
TIMESTAMP_HEADER = "x-hubspot-request-timestamp"

_DECODED = {
    "%3A": ":",
    "%2F": "/",
    "%3F": "?",
    "%40": "@",
    "%21": "!",
    "%24": "$",
    "%27": "'",
    "%28": "(",
    "%29": ")",
    "%2A": "*",
    "%2C": ",",
    "%3B": ";",
}


def signed_url(url: str) -> str:
    """The URL as HubSpot signs it: no fragment, and only the query string has the listed escapes decoded."""
    url = url.split("#", 1)[0]
    path, question, query = url.partition("?")
    if not question:
        return url
    for escaped, plain in _DECODED.items():
        query = query.replace(escaped, plain).replace(escaped.lower(), plain)
    return path + "?" + query


def verify_v3(
    *, secret: str, method: str, url: str, body: bytes, timestamp: str, signature: str, now_ms: int | None = None
) -> bool:
    """True if `signature` is the valid v3 signature of this request and the request is no more than five minutes old (or from the future)."""
    if not (secret and signature and timestamp):
        return False
    try:
        sent_at = int(timestamp)
        text = body.decode("utf-8")
    except ValueError:
        # a timestamp that is not a number, or a body that is not UTF-8 (UnicodeDecodeError is a ValueError)
        return False
    if abs((now_ms if now_ms is not None else int(time.time() * 1000)) - sent_at) > MAX_AGE_MS:
        return False
    message = (method.upper() + signed_url(url) + text + timestamp).encode()
    expected = base64.b64encode(hmac.new(secret.encode(), message, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected.encode(), signature.encode())
