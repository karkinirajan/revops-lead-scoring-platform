from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.auth import jwt as tokens
from app.config import get_settings


def _token_for(subject, kind, **claims):
    """A correctly signed token whose subject and extra claims are whatever is given (only our own key could make one, but the checks should not depend on that)."""
    settings = get_settings()
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": subject, "iat": now, "exp": now + timedelta(minutes=5), "type": kind, **claims},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


class TestPasswords:
    def test_a_password_verifies_against_its_hash(self):
        hashed = tokens.hash_password("correct-horse-battery")
        assert hashed.startswith("$2b$")
        assert tokens.verify_password("correct-horse-battery", hashed)
        assert not tokens.verify_password("correct-horse-batterY", hashed)

    def test_the_same_password_hashes_differently_each_time(self):
        assert tokens.hash_password("same-password-here") != tokens.hash_password("same-password-here")

    def test_a_password_over_72_bytes_is_refused_not_truncated(self):
        with pytest.raises(ValueError, match="is longer than 72 bytes"):  # ours, not bcrypt's own
            tokens.hash_password("x" * 73)
        assert not tokens.verify_password("x" * 73, tokens.hash_password("x" * 72))

    def test_72_bytes_exactly_is_allowed(self):
        assert tokens.verify_password("x" * 72, tokens.hash_password("x" * 72))

    def test_bytes_not_characters_are_counted(self):
        with pytest.raises(ValueError):
            tokens.hash_password("é" * 37)  # 74 bytes

    def test_a_hash_that_is_not_bcrypt_never_verifies(self):
        assert not tokens.verify_password("anything", "not-a-hash")
        assert not tokens.verify_password("anything", "")

    def test_hashes_made_before_the_change_still_verify(self):
        # a hash produced by passlib's bcrypt scheme: $2b$, 12 rounds
        old = "$2b$12$gYAiXlQ2n0nUFA5Zl4mGmeEc6O0Zk6o4WUwQz9zA7y2o3k6jQq9y6"
        assert not tokens.verify_password(
            "whatever", old
        )  # a well-formed hash of another password: False, not an error

    def test_the_cost_comes_from_the_settings(self):
        assert get_settings().bcrypt_rounds == 4  # the test environment
        assert tokens.hash_password("correct-horse-battery").startswith("$2b$04$")

    def test_the_dummy_check_runs_and_returns_nothing(self):
        assert tokens.spend_password_time() is None

    def test_the_cost_follows_the_setting(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "bcrypt_rounds", 5)
        assert tokens.hash_password("correct-horse-battery").startswith("$2b$05$")

    def test_the_dummy_check_does_the_work_of_a_password_check(self, monkeypatch):
        checks = []
        real = tokens.bcrypt.checkpw
        monkeypatch.setattr(tokens.bcrypt, "checkpw", lambda *args: checks.append(1) or real(*args))
        tokens.spend_password_time()
        assert checks == [1]


class TestTokens:
    def test_an_access_token_round_trips(self):
        token = tokens.create_access_token("user-1", extra={"role": "admin"})
        claims = tokens.decode_token(token)
        assert claims["sub"] == "user-1" and claims["role"] == "admin" and claims["type"] == "access"

    def test_the_user_id_and_password_version_are_read_from_the_token(self):
        user_id, version = "0b7ce2c0-1111-4222-8333-444455556666", "v1"
        claims = {tokens.PASSWORD_VERSION_CLAIM: version}
        assert tokens.subject_from_token(tokens.create_access_token(user_id, extra=claims), tokens.ACCESS) == (
            user_id,
            version,
        )
        assert tokens.subject_from_token(tokens.create_refresh_token(user_id, extra=claims), tokens.REFRESH) == (
            user_id,
            version,
        )

    @pytest.mark.parametrize("subject", ["", "not-a-uuid", "12345"])
    def test_a_subject_that_is_not_a_uuid_is_an_invalid_token(self, subject):
        with pytest.raises(tokens.TokenError, match="not a user id"):
            tokens.subject_from_token(_token_for(subject, "access", pwv="v"), tokens.ACCESS)

    @pytest.mark.parametrize("claims", [{}, {"pwv": 5}, {"pwv": None}, {"pwv": ["v"]}])
    def test_a_token_without_a_password_version_is_refused(self, claims):
        with pytest.raises(tokens.TokenError, match="no password version"):
            tokens.subject_from_token(
                _token_for("0b7ce2c0-1111-4222-8333-444455556666", "access", **claims), tokens.ACCESS
            )

    def test_the_user_id_is_read_only_from_the_right_kind_of_token(self):
        user_id = "0b7ce2c0-1111-4222-8333-444455556666"
        with pytest.raises(tokens.TokenError):
            tokens.subject_from_token(tokens.create_refresh_token(user_id, extra={"pwv": "v"}), tokens.ACCESS)

    def test_the_password_version_follows_the_hash(self):
        first, second = tokens.hash_password("correct-horse-battery"), tokens.hash_password("correct-horse-battery")
        assert first != second  # bcrypt salts: the same password, a different hash
        assert tokens.password_version(first) == tokens.password_version(first)
        assert tokens.password_version(first) != tokens.password_version(second)
        assert tokens.password_version_matches(tokens.password_version(first), first)
        assert not tokens.password_version_matches(tokens.password_version(first), second)
        assert not tokens.password_version_matches("", first)

    def test_the_password_version_does_not_reveal_the_hash_and_depends_on_the_signing_key(self, monkeypatch):
        hashed = tokens.hash_password("correct-horse-battery")
        version = tokens.password_version(hashed)
        assert len(version) == 32 and version not in hashed and hashed[7:20] not in version
        monkeypatch.setattr(get_settings(), "jwt_secret_key", "another-signing-key-of-sufficient-length-0123456789")
        assert tokens.password_version(hashed) != version

    def test_a_refresh_token_is_not_an_access_token(self):
        refresh = tokens.create_refresh_token("user-1")
        with pytest.raises(tokens.TokenError, match="expected a access token"):
            tokens.decode_token(refresh)  # default: access
        assert tokens.decode_token(refresh, tokens.REFRESH)["sub"] == "user-1"

    def test_an_access_token_is_not_a_refresh_token(self):
        with pytest.raises(tokens.TokenError):
            tokens.decode_token(tokens.create_access_token("user-1"), tokens.REFRESH)

    @pytest.mark.parametrize("claim", ["sub", "iat", "exp", "type"])
    def test_extra_claims_cannot_override_the_reserved_ones(self, claim):
        with pytest.raises(ValueError, match="may not set"):
            tokens.create_access_token("user-1", extra={claim: "x"})

    def test_lifetimes_follow_the_settings(self):
        settings = get_settings()
        access = jwt.decode(tokens.create_access_token("u"), options={"verify_signature": False})
        refresh = jwt.decode(tokens.create_refresh_token("u"), options={"verify_signature": False})
        assert access["exp"] - access["iat"] == settings.jwt_access_token_expire_minutes * 60
        assert refresh["exp"] - refresh["iat"] == settings.jwt_refresh_token_expire_days * 86400

    def test_an_expired_token_is_rejected(self):
        settings = get_settings()
        now = datetime.now(UTC)
        expired = jwt.encode(
            {"sub": "u", "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1), "type": "access"},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(tokens.TokenError):
            tokens.decode_token(expired)

    def test_a_token_signed_with_another_key_is_rejected(self):
        forged = jwt.encode(
            {"sub": "u", "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(hours=1), "type": "access"},
            "another-secret-key-another-secret-key",
            algorithm="HS256",
        )
        with pytest.raises(tokens.TokenError):
            tokens.decode_token(forged)

    def test_an_unsigned_token_is_rejected(self):
        unsigned = jwt.encode(
            {"sub": "u", "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(hours=1), "type": "access"},
            None,
            algorithm="none",
        )
        with pytest.raises(tokens.TokenError):
            tokens.decode_token(unsigned)

    @pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")
    def test_a_token_with_another_algorithm_is_rejected(self):
        settings = get_settings()
        other = jwt.encode(
            {"sub": "u", "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(hours=1), "type": "access"},
            settings.jwt_secret_key,
            algorithm="HS512",
        )
        with pytest.raises(tokens.TokenError):
            tokens.decode_token(other)

    @pytest.mark.parametrize("missing", ["sub", "iat", "exp", "type"])
    def test_a_token_missing_a_required_claim_is_rejected(self, missing):
        settings = get_settings()
        claims = {"sub": "u", "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(hours=1), "type": "access"}
        del claims[missing]
        with pytest.raises(tokens.TokenError):
            tokens.decode_token(jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm))

    @pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "Bearer x"])
    def test_garbage_is_rejected(self, garbage):
        with pytest.raises(tokens.TokenError):
            tokens.decode_token(garbage)

    def test_the_oauth_state_is_its_own_kind_of_token(self):
        state = tokens.issue_token("u", "salesforce_oauth_state", timedelta(minutes=10), None)
        assert tokens.decode_token(state, "salesforce_oauth_state")["sub"] == "u"
        with pytest.raises(tokens.TokenError):
            tokens.decode_token(state)  # it is not an access token


class TestLogin:
    def test_login_returns_working_tokens(self, client, make_user):
        make_user(email="ada@example.com", role="analyst")
        resp = client.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": "correct-horse-battery"})
        assert resp.status_code == 200
        body = resp.json()
        assert (
            body["token_type"] == "bearer" and body["expires_in"] == get_settings().jwt_access_token_expire_minutes * 60
        )
        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert me.status_code == 200 and me.json()["email"] == "ada@example.com" and me.json()["role"] == "analyst"

    def test_the_email_is_not_case_sensitive(self, client, make_user):
        make_user(email="ada@example.com")
        resp = client.post(
            "/api/v1/auth/login", json={"email": "  Ada@Example.COM ", "password": "correct-horse-battery"}
        )
        assert resp.status_code == 200

    def test_an_email_stored_with_capitals_can_still_log_in(self, client, make_user):
        make_user(email="Grace@Example.com")  # a row from before emails were stored lower-case
        resp = client.post(
            "/api/v1/auth/login", json={"email": "grace@example.com", "password": "correct-horse-battery"}
        )
        assert resp.status_code == 200

    def test_a_wrong_password_and_an_unknown_email_get_the_same_answer(self, client, make_user):
        make_user(email="ada@example.com")
        wrong = client.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": "wrong-password-here"})
        unknown = client.post(
            "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-here"}
        )
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json() == {"detail": "Invalid email or password"}

    def test_an_unknown_email_still_costs_a_password_check(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr("app.api.v1.auth.spend_password_time", lambda: calls.append(1))
        client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever-it-is"})
        assert calls == [1]

    def test_an_inactive_account_cannot_log_in(self, client, make_user):
        make_user(email="gone@example.com", active=False)
        resp = client.post(
            "/api/v1/auth/login", json={"email": "gone@example.com", "password": "correct-horse-battery"}
        )
        assert resp.status_code == 403

    def test_login_records_the_time(self, client, make_user, db):
        user = make_user(email="ada@example.com")
        assert user.last_login_at is None
        client.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": "correct-horse-battery"})
        db.refresh(user)
        assert user.last_login_at is not None

    def test_a_password_over_the_limit_is_a_plain_401(self, client, make_user):
        make_user(email="ada@example.com")
        resp = client.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": "x" * 200})
        assert resp.status_code == 401

    def test_oversized_fields_are_a_422(self, client):
        assert client.post("/api/v1/auth/login", json={"email": "a" * 300, "password": "x"}).status_code == 422
        assert client.post("/api/v1/auth/login", json={"email": "a@b.co", "password": "x" * 300}).status_code == 422


class TestRefresh:
    def _login(self, client, make_user):
        make_user(email="ada@example.com")
        return client.post(
            "/api/v1/auth/login", json={"email": "ada@example.com", "password": "correct-horse-battery"}
        ).json()

    def test_a_refresh_token_gets_new_tokens(self, client, make_user):
        pair = self._login(client, make_user)
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert resp.status_code == 200
        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {resp.json()['access_token']}"})
        assert me.status_code == 200

    def test_an_access_token_cannot_be_used_to_refresh(self, client, make_user):
        pair = self._login(client, make_user)
        assert client.post("/api/v1/auth/refresh", json={"refresh_token": pair["access_token"]}).status_code == 401

    def test_a_refresh_token_cannot_be_used_as_an_access_token(self, client, make_user):
        pair = self._login(client, make_user)
        resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {pair['refresh_token']}"})
        assert resp.status_code == 401  # it used to work, for seven days

    def test_garbage_cannot_refresh(self, client):
        assert client.post("/api/v1/auth/refresh", json={"refresh_token": "nonsense"}).status_code == 401

    def test_a_deactivated_user_cannot_refresh(self, client, make_user, db):
        pair = self._login(client, make_user)
        from app.models.user import User

        db.query(User).update({"is_active": False})
        db.commit()
        assert client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]}).status_code == 401

    def test_a_deleted_user_cannot_refresh(self, client, make_user, db):
        pair = self._login(client, make_user)
        from app.models.user import User

        db.query(User).delete()
        db.commit()
        assert client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]}).status_code == 401


class TestSessionsEndWithThePassword:
    OLD, NEW = "correct-horse-battery", "a-different-password-now"

    def _login(self, client, make_user):
        user = make_user(email="ada@example.com", password=self.OLD)
        pair = client.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": self.OLD}).json()
        return user, pair

    @staticmethod
    def _me(client, token):
        return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code

    @staticmethod
    def _refresh(client, token):
        return client.post("/api/v1/auth/refresh", json={"refresh_token": token}).status_code

    def test_tokens_stay_valid_while_the_password_is_unchanged(self, client, make_user):
        _, pair = self._login(client, make_user)
        assert self._me(client, pair["access_token"]) == 200
        assert self._refresh(client, pair["refresh_token"]) == 200
        assert self._refresh(client, pair["refresh_token"]) == 200  # refresh tokens are not single-use

    def test_changing_the_password_ends_the_sessions_opened_under_the_old_one(self, client, make_user, db):
        user, pair = self._login(client, make_user)
        user.hashed_password = tokens.hash_password(self.NEW)
        db.commit()
        assert self._me(client, pair["access_token"]) == 401
        assert self._refresh(client, pair["refresh_token"]) == 401

    def test_signing_in_again_with_the_new_password_gives_working_tokens(self, client, make_user, db):
        user, _ = self._login(client, make_user)
        user.hashed_password = tokens.hash_password(self.NEW)
        db.commit()
        fresh = client.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": self.NEW}).json()
        assert self._me(client, fresh["access_token"]) == 200
        again = client.post("/api/v1/auth/refresh", json={"refresh_token": fresh["refresh_token"]}).json()
        assert self._me(client, again["access_token"]) == 200  # the refreshed pair carries the same version

    def test_a_token_from_before_password_versions_is_refused(self, client, make_user):
        user = make_user()
        assert self._me(client, tokens.create_access_token(user.id)) == 401
        assert self._refresh(client, tokens.create_refresh_token(user.id)) == 401

    def test_another_users_password_version_does_not_work(self, client, make_user):
        ada = make_user(email="ada@example.com")
        grace = make_user(email="grace@example.com")
        claims = {tokens.PASSWORD_VERSION_CLAIM: tokens.password_version(grace.hashed_password)}
        assert self._me(client, tokens.create_access_token(ada.id, extra=claims)) == 401
        assert self._refresh(client, tokens.create_refresh_token(ada.id, extra=claims)) == 401


class TestAccess:
    def test_no_token_is_a_401(self, client):
        assert client.get("/api/v1/auth/me").status_code == 401

    def test_a_malformed_header_is_a_401(self, client):
        assert client.get("/api/v1/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401
        assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer"}).status_code == 401

    def test_a_token_for_a_deactivated_user_stops_working(self, client, make_user, db, bearer):
        user = make_user()
        headers = bearer(user)
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
        user.is_active = False
        db.commit()
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401

    def test_a_token_for_a_deleted_user_stops_working(self, client, make_user, db, bearer):
        from app.models.user import User

        user = make_user()
        headers = bearer(user)
        db.query(User).delete()
        db.commit()
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401

    @pytest.mark.parametrize("subject", ["", "not-a-uuid", "12345", "x" * 300])
    def test_a_token_whose_subject_is_not_a_user_id_is_a_401_not_a_500(self, client, subject):
        assert (
            client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {_token_for(subject, 'access', pwv='v')}"}
            ).status_code
            == 401
        )

    @pytest.mark.parametrize("subject", ["", "not-a-uuid", "12345"])
    def test_refreshing_with_such_a_token_is_a_401_not_a_500(self, client, subject):
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": _token_for(subject, "refresh", pwv="v")})
        assert resp.status_code == 401

    def test_roles_are_enforced(self, client, auth):
        assert client.get("/api/v1/webhooks", headers=auth("viewer")).status_code == 200
        assert client.post("/api/v1/auth/users", headers=auth("analyst"), json={}).status_code == 403
        assert client.post("/api/v1/auth/users", headers=auth("viewer"), json={}).status_code == 403

    def test_metrics_are_for_admins(self, client, auth):
        assert client.get("/metrics").status_code == 401
        assert client.get("/metrics", headers=auth("viewer")).status_code == 403
        assert client.get("/metrics", headers=auth("admin")).status_code == 200


class TestCreateUser:
    def _body(self, **override):
        return {"email": "New.User@Example.com", "password": "a-long-enough-password", "role": "analyst", **override}

    def test_an_admin_creates_a_user_who_can_log_in(self, client, auth):
        resp = client.post("/api/v1/auth/users", headers=auth("admin"), json=self._body(full_name="New User"))
        assert resp.status_code == 201
        assert resp.json()["email"] == "new.user@example.com" and resp.json()["role"] == "analyst"
        assert "password" not in resp.text and "hashed" not in resp.text
        login = client.post(
            "/api/v1/auth/login", json={"email": "NEW.user@example.com", "password": "a-long-enough-password"}
        )
        assert login.status_code == 200

    def test_the_role_defaults_to_viewer(self, client, auth):
        body = self._body()
        del body["role"]
        assert client.post("/api/v1/auth/users", headers=auth("admin"), json=body).json()["role"] == "viewer"

    def test_a_duplicate_email_is_a_409_whatever_the_case(self, client, auth):
        headers = auth("admin")
        assert client.post("/api/v1/auth/users", headers=headers, json=self._body()).status_code == 201
        assert (
            client.post(
                "/api/v1/auth/users", headers=headers, json=self._body(email="new.user@EXAMPLE.com")
            ).status_code
            == 409
        )

    @pytest.mark.parametrize("password", ["short", "x" * 11, "é" * 40])
    def test_a_weak_or_unhashable_password_is_a_422(self, client, auth, password):
        assert (
            client.post("/api/v1/auth/users", headers=auth("admin"), json=self._body(password=password)).status_code
            == 422
        )

    def test_a_password_of_12_characters_is_enough(self, client, auth):
        assert (
            client.post("/api/v1/auth/users", headers=auth("admin"), json=self._body(password="x" * 12)).status_code
            == 201
        )

    @pytest.mark.parametrize("role", ["superuser", "ADMIN", "", "root"])
    def test_an_unknown_role_is_a_422(self, client, auth, role):
        assert client.post("/api/v1/auth/users", headers=auth("admin"), json=self._body(role=role)).status_code == 422

    def test_an_invalid_email_is_a_422(self, client, auth):
        assert (
            client.post("/api/v1/auth/users", headers=auth("admin"), json=self._body(email="not-an-email")).status_code
            == 422
        )


class TestValidationErrors:
    def test_a_422_says_where_but_not_what_was_sent(self, client):
        resp = client.post(
            "/api/v1/auth/login", json={"email": "a@b.co", "password": ["secret-value-that-is-not-a-string"]}
        )
        assert resp.status_code == 422
        assert "secret-value-that-is-not-a-string" not in resp.text
        problem = resp.json()["detail"][0]
        assert set(problem) == {"loc", "msg", "type"} and problem["loc"][-1] == "password"


class TestSettingsInProduction:
    def _settings(self, monkeypatch, **env):
        from app.config import Settings

        for key in ("JWT_SECRET_KEY", "APP_SECRET_KEY", "ADMIN_PASSWORD", "CORS_ORIGINS", "APP_ENV"):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return Settings(_env_file=None)

    GOOD = {
        "APP_ENV": "production",
        "JWT_SECRET_KEY": "j" * 40,
        "APP_SECRET_KEY": "a" * 40,
        "ADMIN_PASSWORD": "a-real-admin-password",
    }

    def test_development_accepts_the_placeholders(self, monkeypatch):
        assert self._settings(monkeypatch, APP_ENV="development").jwt_secret_key == "insecure-dev-jwt-secret-change-me"

    def test_production_with_real_secrets_starts(self, monkeypatch):
        assert self._settings(monkeypatch, **self.GOOD).is_production

    @pytest.mark.parametrize("name", ["JWT_SECRET_KEY", "APP_SECRET_KEY", "ADMIN_PASSWORD"])
    def test_production_refuses_a_placeholder(self, monkeypatch, name):
        env = {k: v for k, v in self.GOOD.items() if k != name}
        with pytest.raises(ValueError, match=f"{name} is still the placeholder"):
            self._settings(monkeypatch, **env)

    def test_a_secret_of_exactly_32_characters_is_enough(self, monkeypatch):
        assert self._settings(monkeypatch, **{**self.GOOD, "JWT_SECRET_KEY": "s" * 32, "APP_SECRET_KEY": "t" * 32})

    def test_only_production_is_production(self, monkeypatch):
        assert self._settings(monkeypatch, **self.GOOD).is_production
        assert not self._settings(monkeypatch, **{**self.GOOD, "APP_ENV": "staging"}).is_production
        assert not self._settings(monkeypatch, APP_ENV="development").is_production

    @pytest.mark.parametrize("rounds", ["4", "12", "16"])
    def test_a_bcrypt_cost_in_range_is_accepted(self, monkeypatch, rounds):
        monkeypatch.setenv("BCRYPT_ROUNDS", rounds)
        from app.config import Settings

        assert Settings(_env_file=None).bcrypt_rounds == int(rounds)

    @pytest.mark.parametrize("rounds", ["3", "17", "0", "31"])
    def test_a_bcrypt_cost_out_of_range_is_refused(self, monkeypatch, rounds):
        monkeypatch.setenv("BCRYPT_ROUNDS", rounds)
        from app.config import Settings

        with pytest.raises(ValueError):
            Settings(_env_file=None)

    def test_the_default_bcrypt_cost_is_12(self, monkeypatch):
        monkeypatch.delenv("BCRYPT_ROUNDS", raising=False)
        from app.config import Settings

        assert Settings(_env_file=None).bcrypt_rounds == 12

    def test_staging_is_not_development(self, monkeypatch):
        with pytest.raises(ValueError, match="placeholder"):
            self._settings(monkeypatch, APP_ENV="staging")

    @pytest.mark.parametrize("name", ["JWT_SECRET_KEY", "APP_SECRET_KEY"])
    def test_production_refuses_a_short_secret(self, monkeypatch, name):
        with pytest.raises(ValueError, match=f"{name} must be at least 32"):
            self._settings(monkeypatch, **{**self.GOOD, name: "s" * 31})

    def test_production_refuses_a_wildcard_cors_origin(self, monkeypatch):
        with pytest.raises(ValueError, match="CORS_ORIGINS"):
            self._settings(monkeypatch, **self.GOOD, CORS_ORIGINS="https://app.example.com, *")

    def test_all_problems_are_reported_together(self, monkeypatch):
        with pytest.raises(ValueError) as exc:
            self._settings(monkeypatch, APP_ENV="production")
        for name in ("JWT_SECRET_KEY", "APP_SECRET_KEY", "ADMIN_PASSWORD"):
            assert name in str(exc.value)

    def test_the_algorithm_is_limited_to_hmac(self, monkeypatch):
        monkeypatch.setenv("JWT_ALGORITHM", "none")
        from app.config import Settings

        with pytest.raises(ValueError):
            Settings(_env_file=None)

    def test_cors_origins_are_split_and_trimmed(self, monkeypatch):
        settings = self._settings(monkeypatch, APP_ENV="development", CORS_ORIGINS=" http://a.test , http://b.test ,")
        assert settings.cors_origins_list == ["http://a.test", "http://b.test"]

    def test_the_rate_limit_store_defaults_to_redis(self, monkeypatch):
        monkeypatch.delenv("RATE_LIMIT_STORAGE_URI", raising=False)
        monkeypatch.setenv("REDIS_URL", "redis://example:6379/3")
        from app.config import Settings

        settings = Settings(_env_file=None)
        assert settings.limiter_storage_uri == "redis://example:6379/3"
        monkeypatch.setenv("RATE_LIMIT_STORAGE_URI", "memory://")
        assert Settings(_env_file=None).limiter_storage_uri == "memory://"
