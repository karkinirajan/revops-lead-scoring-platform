"""Initial schema — all core tables.

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- users ----
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255)),
        sa.Column("role", sa.String(50), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ---- companies ----
    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("source_system", sa.String(50), nullable=False),
        sa.Column("source_record_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("domain", sa.String(255)),
        sa.Column("industry", sa.String(100)),
        sa.Column("employee_count", sa.Integer),
        sa.Column("annual_revenue", sa.Integer),
        sa.Column("country", sa.String(100)),
        sa.Column("city", sa.String(100)),
        sa.Column("size_tier", sa.String(20)),
        sa.Column("lifecycle_stage", sa.String(50)),
        sa.Column("hubspot_company_id", sa.String(50)),
        sa.Column("crm_owner_id", sa.String(50)),
        sa.Column("extra", postgresql.JSONB),
        sa.Column("schema_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_companies_source_record_id", "companies", ["source_record_id"])
    op.create_index("ix_companies_name", "companies", ["name"])
    op.create_index("ix_companies_domain", "companies", ["domain"])
    op.create_index("ix_companies_hubspot_company_id", "companies", ["hubspot_company_id"])

    # ---- contacts ----
    op.create_table(
        "contacts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("source_system", sa.String(50), nullable=False),
        sa.Column("source_record_id", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("first_name", sa.String(255)),
        sa.Column("last_name", sa.String(255)),
        sa.Column("job_title", sa.String(255)),
        sa.Column("phone", sa.String(50)),
        sa.Column("company_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("companies.id")),
        sa.Column("lifecycle_stage", sa.String(50)),
        sa.Column("lead_status", sa.String(50)),
        sa.Column("hubspot_contact_id", sa.String(50)),
        sa.Column("crm_owner_id", sa.String(50)),
        sa.Column("last_activity_at", sa.DateTime(timezone=True)),
        sa.Column("extra", postgresql.JSONB),
        sa.Column("schema_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_system", "source_record_id", name="uq_contact_source"),
    )
    op.create_index("ix_contacts_email", "contacts", ["email"])
    op.create_index("ix_contacts_source_record_id", "contacts", ["source_record_id"])
    op.create_index("ix_contacts_company_id", "contacts", ["company_id"])
    op.create_index("ix_contacts_hubspot_contact_id", "contacts", ["hubspot_contact_id"])

    # ---- contact_features ----
    op.create_table(
        "contact_features",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_calls_1d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("api_calls_7d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("api_calls_30d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("page_views_7d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("page_views_30d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pricing_page_visited", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("docs_page_visits_7d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("email_opens_7d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("email_clicks_7d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("email_opens_30d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("demo_requested", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("free_trial_active", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("integration_connected", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("integrations_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("days_since_last_activity", sa.Integer, nullable=False, server_default="999"),
        sa.Column("days_since_last_email_open", sa.Integer, nullable=False, server_default="999"),
        sa.Column("sessions_7d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_session_duration_seconds", sa.Float, nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("window_start", sa.DateTime(timezone=True)),
        sa.Column("window_end", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_contact_features_contact_id", "contact_features", ["contact_id"], unique=True)

    # ---- raw_events ----
    op.create_table(
        "raw_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("source_system", sa.String(50), nullable=False),
        sa.Column("source_record_id", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("event_time", sa.DateTime(timezone=True)),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("raw_payload", postgresql.JSONB, nullable=False),
        sa.Column("processed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("processing_error", sa.Text),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("quarantined", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("quarantine_reason", sa.Text),
        sa.Column("trace_id", sa.String(64)),
        sa.Column("job_id", sa.String(64)),
    )
    op.create_index("ix_raw_events_source_system", "raw_events", ["source_system"])
    op.create_index("ix_raw_events_source_record_id", "raw_events", ["source_record_id"])
    op.create_index("ix_raw_events_ingested_at", "raw_events", ["ingested_at"])
    op.create_index("ix_raw_events_processed", "raw_events", ["processed"])

    # ---- worker_checkpoints ----
    op.create_table(
        "worker_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("connector_id", sa.String(100), nullable=False),
        sa.Column("last_successful_watermark", sa.String(255)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_status", sa.String(20)),
        sa.Column("records_processed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("meta", postgresql.JSONB),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_worker_checkpoints_connector_id", "worker_checkpoints", ["connector_id"], unique=True)

    # ---- scoring_runs ----
    op.create_table(
        "scoring_runs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("model_version", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("filter_segment", sa.String(50)),
        sa.Column("is_shadow", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("triggered_by", sa.String(100)),
        sa.Column("total_contacts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("scored_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("duration_seconds", sa.Float),
        sa.Column("error_detail", sa.Text),
    )

    # ---- lead_scores ----
    op.create_table(
        "lead_scores",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("companies.id")),
        sa.Column("scoring_run_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("scoring_runs.id")),
        sa.Column("lead_score", sa.Integer, nullable=False),
        sa.Column("priority_tier", sa.String(10), nullable=False),
        sa.Column("model_version", sa.String(20), nullable=False),
        sa.Column("score_reason", sa.Text),
        sa.Column("feature_contributions", postgresql.JSONB),
        sa.Column("feature_snapshot", postgresql.JSONB),
        sa.Column("recommended_action", sa.String(100)),
        sa.Column("is_shadow", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("feature_freshness_at", sa.DateTime(timezone=True)),
        sa.Column("synced_to_hubspot_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_lead_scores_contact_id", "lead_scores", ["contact_id"])
    op.create_index("ix_lead_scores_priority_tier", "lead_scores", ["priority_tier"])
    op.create_index("ix_lead_scores_scored_at", "lead_scores", ["scored_at"])
    op.create_index("ix_lead_scores_model_version", "lead_scores", ["model_version"])

    # ---- audit_logs ----
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("actor_id", sa.String(64)),
        sa.Column("actor_email", sa.String(255)),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("before_value", postgresql.JSONB),
        sa.Column("after_value", postgresql.JSONB),
        sa.Column("trace_id", sa.String(64)),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_entity_id", "audit_logs", ["entity_id"])
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])

    # ---- crm_sync_logs ----
    op.create_table(
        "crm_sync_logs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("contact_id", sa.String(64)),
        sa.Column("company_id", sa.String(64)),
        sa.Column("crm_system", sa.String(50), nullable=False),
        sa.Column("crm_record_id", sa.String(50)),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("http_status_code", sa.Integer),
        sa.Column("error_message", sa.Text),
        sa.Column("payload_hash", sa.String(64)),
        sa.Column("attempt_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("job_id", sa.String(64)),
    )
    op.create_index("ix_crm_sync_logs_status", "crm_sync_logs", ["status"])
    op.create_index("ix_crm_sync_logs_synced_at", "crm_sync_logs", ["synced_at"])


def downgrade() -> None:
    op.drop_table("crm_sync_logs")
    op.drop_table("audit_logs")
    op.drop_table("lead_scores")
    op.drop_table("scoring_runs")
    op.drop_table("worker_checkpoints")
    op.drop_table("raw_events")
    op.drop_table("contact_features")
    op.drop_table("contacts")
    op.drop_table("companies")
    op.drop_table("users")
