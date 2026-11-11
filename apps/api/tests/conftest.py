"""Test setup: a private environment, a real PostgreSQL, and a database session per test.

The API is tested against PostgreSQL itself (its models use JSONB and UUID columns), with the Alembic migrations as the schema. Where the database comes from:

* `TEST_DATABASE_URL`, if set (CI points it at a service container); otherwise
* a throwaway cluster started from the PostgreSQL binaries on the machine (`initdb`, `pg_ctl`) in a temporary folder, listening on a unix socket only; otherwise
* the tests that need a database are skipped, with the reason.

Nothing here talks to Redis, Celery, Anthropic or any CRM: task dispatch is replaced by recorders and HTTP calls by fakes in the tests that need them.
"""

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = API_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:  # `workers.*` is imported by the API
    sys.path.insert(0, str(REPO_ROOT))

# ---- the environment the app is imported with (before `app.config` reads it; values here win over a developer's .env) ----
TEST_ENVIRONMENT = {
    "APP_ENV": "development",
    "JWT_SECRET_KEY": "test-jwt-secret-key-with-more-than-32-characters",
    "BCRYPT_ROUNDS": "4",
    "RATE_LIMIT_STORAGE_URI": "memory://",
    "RATE_LIMIT_PER_MINUTE": "100000",
    "RATE_LIMIT_LOGIN_PER_MINUTE": "100000",
    "AI_INTELLIGENCE_RATE_LIMIT_PER_MINUTE": "100000",
    "REDIS_URL": "redis://127.0.0.1:1/0",  # a closed port: refuses at once
    "CELERY_BROKER_URL": "redis://127.0.0.1:1/0",
    "CELERY_RESULT_BACKEND": "redis://127.0.0.1:1/0",
    "ANTHROPIC_API_KEY": "",
    "HUBSPOT_ACCESS_TOKEN": "",
    "HUBSPOT_WEBHOOK_SECRET": "",
    "SALESFORCE_CLIENT_ID": "",
    "SALESFORCE_CLIENT_SECRET": "",
    "SALESFORCE_REDIRECT_URI": "",
    "S3_ENDPOINT_URL": "",
    "ML_MODELS_DIR": str(Path(tempfile.gettempdir()) / "revops-test-models"),
}
os.environ.update(TEST_ENVIRONMENT)

_DATABASE_SKIP_REASON: str | None = None


def _find_postgres_binary(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for candidate in sorted(Path("/usr/lib/postgresql").glob(f"*/bin/{name}"), reverse=True):
        return str(candidate)
    return None


def _start_local_postgres() -> str:
    initdb, pg_ctl = _find_postgres_binary("initdb"), _find_postgres_binary("pg_ctl")
    if not (initdb and pg_ctl):
        raise RuntimeError("PostgreSQL binaries (initdb, pg_ctl) not found and TEST_DATABASE_URL is not set")
    base = Path(tempfile.mkdtemp(prefix="revops-pg-"))
    data, sockets = base / "data", base / "sock"
    sockets.mkdir()
    subprocess.run(
        [initdb, "-D", str(data), "-U", "revops", "--auth=trust", "-E", "UTF8", "--no-sync"],
        check=True,
        capture_output=True,
    )
    options = f"-c listen_addresses='' -c unix_socket_directories='{sockets}' -c fsync=off -c synchronous_commit=off -c full_page_writes=off"
    subprocess.run(
        [pg_ctl, "-D", str(data), "-o", options, "-l", str(base / "postgres.log"), "-w", "start"],
        check=True,
        capture_output=True,
    )

    def stop() -> None:
        subprocess.run([pg_ctl, "-D", str(data), "-m", "immediate", "stop"], capture_output=True)
        shutil.rmtree(base, ignore_errors=True)

    atexit.register(stop)

    import psycopg2

    conn = psycopg2.connect(host=str(sockets), user="revops", dbname="postgres")
    try:
        conn.autocommit = True  # CREATE DATABASE cannot run inside a transaction
        conn.cursor().execute("CREATE DATABASE revops_test")
    finally:
        conn.close()
    return f"postgresql+psycopg2://revops@/revops_test?host={sockets}"


def _resolve_database_url() -> str:
    global _DATABASE_SKIP_REASON
    if os.environ.get("TEST_DATABASE_URL"):
        return os.environ["TEST_DATABASE_URL"]
    try:
        return _start_local_postgres()
    except Exception as exc:  # no PostgreSQL available: the database tests are skipped
        _DATABASE_SKIP_REASON = f"no test database: {exc}"
        return "postgresql+psycopg2://revops@127.0.0.1:1/revops_test"


os.environ["DATABASE_URL"] = _resolve_database_url()


@pytest.fixture(autouse=True)
def _no_outside_network(monkeypatch):
    """A test must never reach the internet (a real Anthropic, HubSpot or Salesforce call): only unix sockets and loopback addresses may be connected to."""
    import socket

    real_connect = socket.socket.connect

    def guarded(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            host = address[0] if isinstance(address, tuple) else address
            if host not in ("127.0.0.1", "::1", "localhost"):
                raise AssertionError(f"a test tried to connect to {host}: use a fake")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture(scope="session")
def _schema():
    """Create the schema by running every Alembic migration once (so the migrations are tested too)."""
    if _DATABASE_SKIP_REASON:
        pytest.skip(_DATABASE_SKIP_REASON)
    from alembic import command
    from alembic.config import Config

    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    command.upgrade(config, "head")
    yield


@pytest.fixture()
def db(_schema):
    """A session whose changes, commits included, are rolled back at the end of the test."""
    from sqlalchemy.orm import Session

    from app.database import engine

    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture()
def client(db):
    """A test client whose requests use the test's session."""
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def make_user(db):
    """Create a user in the test database and return it."""
    from app.auth.jwt import hash_password
    from app.models.user import User

    def _make(email="user@example.com", role="viewer", password="correct-horse-battery", active=True):
        user = User(
            email=email, hashed_password=hash_password(password), role=role, is_active=active, full_name="Test User"
        )
        db.add(user)
        db.commit()
        return user

    return _make


@pytest.fixture()
def bearer():
    """Authorization headers with an access token for the given user, carrying what the login endpoint puts in one."""
    from app.auth.jwt import PASSWORD_VERSION_CLAIM, create_access_token, password_version

    def _bearer(user):
        claims = {"role": user.role, PASSWORD_VERSION_CLAIM: password_version(user.hashed_password)}
        return {"Authorization": f"Bearer {create_access_token(user.id, extra=claims)}"}

    return _bearer


@pytest.fixture()
def auth(make_user, bearer):
    """Authorization headers for a new user with the given role."""

    def _auth(role="viewer", email=None):
        return bearer(make_user(email=email or f"{role}-{uuid.uuid4().hex[:8]}@example.com", role=role))

    return _auth


@pytest.fixture()
def public_dns(monkeypatch):
    """Make every host name resolve to a public address, so URL checks do not depend on the network."""

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(2, 1, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr("app.security.urls.socket.getaddrinfo", fake_getaddrinfo)


@pytest.fixture()
def make_contact(db):
    """Create a contact (optionally with a company, features and a score) and return it."""
    from app.models.company import Company
    from app.models.contact import Contact, ContactFeature
    from app.models.scoring import LeadScore

    counter = iter(range(1, 10_000))

    def _make(
        email=None,
        source_system="hubspot",
        source_record_id=None,
        company=None,
        score=None,
        tier="HOT",
        shadow=False,
        features=None,
        **fields,
    ):
        n = next(counter)
        company_row = None
        if company:
            company_row = Company(
                source_system="hubspot",
                source_record_id=f"co-{n}",
                name=company["name"],
                domain=company.get("domain", f"co{n}.test"),
            )
            company_row.industry = company.get("industry")
            company_row.size_tier = company.get("size_tier")
            db.add(company_row)
            db.flush()
        contact = Contact(
            source_system=source_system,
            source_record_id=source_record_id or f"rec-{n}",
            email=email or f"lead{n}@example.com",
            company_id=company_row.id if company_row else None,
            **fields,
        )
        db.add(contact)
        db.flush()
        if features is not None:
            db.add(ContactFeature(contact_id=contact.id, **features))
        if score is not None:
            db.add(
                LeadScore(
                    contact_id=contact.id,
                    lead_score=score,
                    priority_tier=tier,
                    model_version="1.0.0",
                    score_reason="test",
                    is_shadow=shadow,
                )
            )
        db.commit()
        return contact

    return _make


class BorrowedSession:
    """Lends the test's session to worker code that opens and closes its own sessions (closing does nothing, so the test keeps its data)."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


@pytest.fixture()
def worker_db(db, monkeypatch):
    """Make `app.database.SessionLocal()` return the test's session, so tasks that open their own sessions work inside the test transaction."""
    monkeypatch.setattr("app.database.SessionLocal", lambda: BorrowedSession(db))
    return db
