"""Add conversions, webhooks, model_registry, crm_connections tables.

Revision ID: 002
Revises: 001
Create Date: 2026-04-08 00:00:00

New tables:
  - conversions         (Feature 2: Conversion Feedback Loop)
  - webhooks            (Feature 3: Webhook Delivery Engine)
  - webhook_delivery_logs
  - model_registry      (Feature 1: ML Model v2)
  - crm_connections     (Feature 4: Salesforce / multi-CRM)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    # ---- conversions ----
    op.create_table(
        "conversions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("contacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deal_value", sa.Float),
        sa.Column("days_to_close", sa.Integer),
        sa.Column("plan_tier", sa.String(50)),
        sa.Column("score_at_conversion", sa.Integer),
        sa.Column("tier_at_conversion", sa.String(10)),
        sa.Column("model_version_at_conversion", sa.String(20)),
        sa.Column("source", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("crm_deal_id", sa.String(100)),
        sa.Column("notes", sa.Text),
        sa.Column("extra", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_conversions_contact_id", "conversions", ["contact_id"])
    op.create_index("ix_conversions_converted_at", "conversions", ["converted_at"])
    op.create_index("ix_conversions_crm_deal_id", "conversions", ["crm_deal_id"])
    op.create_index("ix_conversions_tier_at_conversion", "conversions", ["tier_at_conversion"])

    # ---- webhooks ----
    op.create_table(
        "webhooks",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("created_by", sa.String(64)),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("secret", sa.String(255)),
        sa.Column("events", sa.String(500), nullable=False, server_default="tier_crossed"),
        sa.Column("tier_filter", sa.String(100)),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("total_deliveries", sa.Integer, nullable=False, server_default="0"),
        sa.Column("successful_deliveries", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_deliveries", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_webhooks_status", "webhooks", ["status"])
    op.create_index("ix_webhooks_created_by", "webhooks", ["created_by"])

    # ---- webhook_delivery_logs ----
    op.create_table(
        "webhook_delivery_logs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("webhook_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("contact_id", sa.String(64)),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("http_status_code", sa.Integer),
        sa.Column("response_body", sa.Text),
        sa.Column("error_message", sa.Text),
        sa.Column("attempt_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_webhook_delivery_logs_webhook_id", "webhook_delivery_logs", ["webhook_id"])
    op.create_index("ix_webhook_delivery_logs_status", "webhook_delivery_logs", ["status"])
    op.create_index("ix_webhook_delivery_logs_event_type", "webhook_delivery_logs", ["event_type"])
    op.create_index("ix_webhook_delivery_logs_contact_id", "webhook_delivery_logs", ["contact_id"])
    op.create_index("ix_webhook_delivery_logs_created_at", "webhook_delivery_logs", ["created_at"])

    # ---- model_registry ----
    op.create_table(
        "model_registry",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("version", sa.String(30), nullable=False),
        sa.Column("algorithm", sa.String(50), nullable=False, server_default="xgboost"),
        sa.Column("stage", sa.String(20), nullable=False, server_default="training"),
        sa.Column("training_rows", sa.Integer),
        sa.Column("positive_rate", sa.Float),
        sa.Column("precision_hot", sa.Float),
        sa.Column("recall_hot", sa.Float),
        sa.Column("roc_auc", sa.Float),
        sa.Column("f1_score", sa.Float),
        sa.Column("feature_importances", postgresql.JSONB),
        sa.Column("artifact_path", sa.String(1024)),
        sa.Column("artifact_size_bytes", sa.Integer),
        sa.Column("trained_by", sa.String(100)),
        sa.Column("training_config", postgresql.JSONB),
        sa.Column("notes", sa.Text),
        sa.Column("trained_at", sa.DateTime(timezone=True)),
        sa.Column("promoted_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("version", name="uq_model_registry_version"),
    )
    op.create_index("ix_model_registry_stage", "model_registry", ["stage"])
    op.create_index("ix_model_registry_version", "model_registry", ["version"])

    # ---- crm_connections ----
    op.create_table(
        "crm_connections",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("crm_type", sa.String(30), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("org_id", sa.String(100)),
        sa.Column("access_token", sa.Text),
        sa.Column("refresh_token", sa.Text),
        sa.Column("token_expires_at", sa.DateTime(timezone=True)),
        sa.Column("instance_url", sa.String(500)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("sync_direction", sa.String(20), nullable=False, server_default="bidirectional"),
        sa.Column("score_field_name", sa.String(100), nullable=False, server_default="revops_lead_score"),
        sa.Column("tier_field_name", sa.String(100), nullable=False, server_default="revops_priority_tier"),
        sa.Column("field_mapping", postgresql.JSONB),
        sa.Column("last_inbound_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_outbound_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_sync_error", sa.Text),
        sa.Column("total_records_synced", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_crm_connections_crm_type", "crm_connections", ["crm_type"])
    op.create_index("ix_crm_connections_org_id", "crm_connections", ["org_id"])
    op.create_index("ix_crm_connections_is_active", "crm_connections", ["is_active"])


def downgrade() -> None:
    op.drop_table("crm_connections")
    op.drop_table("model_registry")
    op.drop_table("webhook_delivery_logs")
    op.drop_table("webhooks")
    op.drop_table("conversions")
