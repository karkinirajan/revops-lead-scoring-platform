"""Encryption of secrets stored in the database (CRM access and refresh tokens).

Values are encrypted with Fernet (AES-128-CBC with an HMAC) under a key derived from `APP_SECRET_KEY`, and stored as `enc:v1:<token>`. A value without that prefix
is read as it is, so rows written before encryption existed keep working and are encrypted the next time they are saved. Changing APP_SECRET_KEY makes the stored
values unreadable (reading them raises ValueError): reconnect the integrations after rotating it.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.config import get_settings

PREFIX = "enc:v1:"


@lru_cache
def _fernet(secret: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def encrypt(value: str) -> str:
    return PREFIX + _fernet(get_settings().app_secret_key).encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value.startswith(PREFIX):
        return value  # written before encryption existed
    try:
        return _fernet(get_settings().app_secret_key).decrypt(value[len(PREFIX) :].encode()).decode()
    except InvalidToken:
        raise ValueError(
            "a stored secret cannot be decrypted: APP_SECRET_KEY changed or the value is damaged"
        ) from None


class EncryptedText(TypeDecorator):
    """A text column whose value is encrypted in the database and plain in Python."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        return None if value is None else encrypt(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:
        return None if value is None else decrypt(value)
