"""The models and the Alembic migrations describe the same database."""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from tests.conftest import API_DIR


def _config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    return config


def test_the_migrations_produce_exactly_the_schema_the_models_declare(_schema):
    import app.models  # noqa: F401 - registers every table
    from app.database import Base, engine

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)
    assert differences == [], f"the models and the migrations disagree: {differences}"


def test_the_database_is_at_the_latest_revision(_schema):
    from alembic.script import ScriptDirectory

    from app.database import engine

    head = ScriptDirectory.from_config(_config()).get_current_head()
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == head == "003"


def test_there_is_a_single_migration_line(_schema):
    from alembic.script import ScriptDirectory

    assert len(ScriptDirectory.from_config(_config()).get_heads()) == 1


def test_the_last_migration_can_be_undone_and_redone(_schema):
    from app.database import engine

    config = _config()
    command.downgrade(config, "002")
    with engine.connect() as connection:
        names = {index["name"] for index in __import__("sqlalchemy").inspect(connection).get_indexes("audit_logs")}
    assert "ix_audit_logs_action" not in names
    command.upgrade(config, "head")
    with engine.connect() as connection:
        names = {index["name"] for index in __import__("sqlalchemy").inspect(connection).get_indexes("audit_logs")}
    assert "ix_audit_logs_action" in names


def test_orphaned_delivery_logs_are_cleaned_up_by_the_migration(_schema):
    """Upgrading a database that has logs of deleted webhooks must not fail on the new foreign key."""
    from sqlalchemy import text

    from app.database import engine

    config = _config()
    command.downgrade(config, "002")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO webhook_delivery_logs (id, webhook_id, event_type, payload, status, attempt_number) "
                "VALUES (gen_random_uuid(), gen_random_uuid(), 'tier_crossed', '{}', 'pending', 1)"
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM webhook_delivery_logs")).scalar() == 0


@pytest.mark.parametrize("table", ["lead_scores", "scoring_runs", "raw_events"])
def test_flags_are_real_booleans(_schema, table):
    from sqlalchemy import inspect

    from app.database import engine

    columns = {c["name"]: str(c["type"]) for c in inspect(engine).get_columns(table)}
    flag = "processed" if table == "raw_events" else "is_shadow"
    assert columns[flag] == "BOOLEAN"
