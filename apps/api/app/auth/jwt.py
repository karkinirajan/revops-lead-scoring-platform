"""Password hashing and JSON Web Tokens.

Passwords are hashed with bcrypt (the existing `$2b$` hashes stay valid). bcrypt only looks at the first 72 bytes, so longer passwords are refused rather than
silently truncated. Tokens are signed with the configured HMAC algorithm; the algorithm is fixed on decode (never read from the token), and a token must say what
it is for: an access token cannot be used where a refresh token is expected, or the other way round.
"""

import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import bcrypt
import jwt
from jwt import InvalidTokenError

from app.config import get_settings

ACCESS = "access"
REFRESH = "refresh"
RESERVED_CLAIMS = frozenset({"sub", "iat", "exp", "type"})
MAX_PASSWORD_BYTES = 72  # bcrypt ignores everything after this

TokenError = InvalidTokenError


def hash_password(password: str) -> str:
    raw = password.encode()
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password is longer than {MAX_PASSWORD_BYTES} bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=get_settings().bcrypt_rounds)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:  # a password over 72 bytes, or a stored value that is not a bcrypt hash
        return False


@lru_cache
def _dummy_hash() -> str:
    return hash_password("not-a-real-password")


def spend_password_time() -> None:
    """Do the work of a password check for an account that does not exist, so that a login for an unknown email takes as long as one for a known email."""
    verify_password("not-the-password", _dummy_hash())


def issue_token(subject: str, kind: str, lifetime: timedelta, extra: dict[str, Any] | None) -> str:
    settings = get_settings()
    if extra and RESERVED_CLAIMS & extra.keys():
        raise ValueError(f"extra claims may not set {sorted(RESERVED_CLAIMS & extra.keys())}")
    now = datetime.now(UTC)
    payload: dict[str, Any] = {**(extra or {}), "sub": subject, "iat": now, "exp": now + lifetime, "type": kind}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    return issue_token(subject, ACCESS, timedelta(minutes=get_settings().jwt_access_token_expire_minutes), extra)


def create_refresh_token(subject: str) -> str:
    return issue_token(subject, REFRESH, timedelta(days=get_settings().jwt_refresh_token_expire_days), None)


def decode_token(token: str, expected_type: str = ACCESS) -> dict[str, Any]:
    """Validate a token's signature, expiry and purpose and return its claims. Raises TokenError (a `jwt.InvalidTokenError`) for anything wrong with it."""
    settings = get_settings()
    claims = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "iat", "sub", "type"]},
    )
    if claims["type"] != expected_type:
        raise InvalidTokenError(f"expected a {expected_type} token")
    return claims


def user_id_from_token(token: str, expected_type: str) -> str:
    """The id of the user a token was issued to. Ids are UUIDs: any other subject cannot be a user, and would reach the database as a malformed value (a 500)."""
    subject = decode_token(token, expected_type)["sub"]
    try:
        uuid.UUID(subject)
    except (ValueError, AttributeError, TypeError) as exc:
        raise InvalidTokenError("the subject is not a user id") from exc
    return subject
