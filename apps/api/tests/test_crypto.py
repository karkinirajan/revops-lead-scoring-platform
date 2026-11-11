import pytest

from app.config import get_settings
from app.models.crm_connection import CrmConnection
from app.security import crypto


class TestEncryptDecrypt:
    def test_a_value_round_trips(self):
        assert crypto.decrypt(crypto.encrypt("00D-access-token")) == "00D-access-token"

    def test_the_stored_form_is_prefixed_and_hides_the_value(self):
        stored = crypto.encrypt("00D-access-token")
        assert stored.startswith("enc:v1:") and "00D-access-token" not in stored

    def test_the_same_value_encrypts_differently_each_time(self):
        assert crypto.encrypt("same") != crypto.encrypt("same")

    def test_unicode_and_empty_values(self):
        assert crypto.decrypt(crypto.encrypt("tökén-日本")) == "tökén-日本"
        assert crypto.decrypt(crypto.encrypt("")) == ""

    def test_a_value_written_before_encryption_is_read_as_it_is(self):
        assert crypto.decrypt("plain-old-token") == "plain-old-token"

    def test_a_changed_key_is_a_clear_error(self, monkeypatch):
        stored = crypto.encrypt("secret-token")
        monkeypatch.setattr(get_settings(), "app_secret_key", "a-completely-different-secret-key-value")
        with pytest.raises(ValueError, match="cannot be decrypted"):
            crypto.decrypt(stored)

    def test_a_damaged_value_is_a_clear_error(self):
        with pytest.raises(ValueError, match="cannot be decrypted"):
            crypto.decrypt("enc:v1:not-a-fernet-token")

    def test_the_error_does_not_contain_the_value(self):
        stored = crypto.encrypt("secret-token")
        with pytest.raises(ValueError) as exc:
            crypto.decrypt(stored[:-4] + "AAAA")
        assert "secret-token" not in str(exc.value)


class TestEncryptedColumn:
    def test_tokens_are_encrypted_in_the_database_and_plain_in_python(self, db):
        conn = CrmConnection(crm_type="hubspot", name="HubSpot", access_token="access-123", refresh_token="refresh-456")
        db.add(conn)
        db.commit()
        db.expire_all()

        assert db.get(CrmConnection, conn.id).access_token == "access-123"
        raw = db.execute(
            crypto_text("SELECT access_token, refresh_token FROM crm_connections WHERE id = :id"), {"id": conn.id}
        ).one()
        assert raw[0].startswith("enc:v1:") and raw[1].startswith("enc:v1:")
        assert "access-123" not in raw[0] and "refresh-456" not in raw[1]

    def test_a_null_token_stays_null(self, db):
        conn = CrmConnection(crm_type="hubspot", name="HubSpot", access_token="a", refresh_token=None)
        db.add(conn)
        db.commit()
        raw = db.execute(
            crypto_text("SELECT refresh_token FROM crm_connections WHERE id = :id"), {"id": conn.id}
        ).scalar()
        assert raw is None
        db.expire_all()
        assert db.get(CrmConnection, conn.id).refresh_token is None  # and it reads back as None, not as ""

    def test_a_row_written_in_plain_text_is_still_readable(self, db):
        conn = CrmConnection(crm_type="hubspot", name="Legacy", access_token="x")
        db.add(conn)
        db.commit()
        db.execute(
            crypto_text("UPDATE crm_connections SET access_token = 'legacy-plain' WHERE id = :id"), {"id": conn.id}
        )
        db.expire_all()
        assert db.get(CrmConnection, conn.id).access_token == "legacy-plain"


def crypto_text(sql):
    from sqlalchemy import text

    return text(sql)
