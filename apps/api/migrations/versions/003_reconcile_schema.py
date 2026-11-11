"""Reconcile the database with the models.

The first two migrations left the database different from the models:

  - webhook_delivery_logs.webhook_id had no foreign key to webhooks (the model declares ON DELETE CASCADE). Delivery logs whose webhook no longer exists are
    deleted first, since nothing can reach them, and then the foreign key is added.
  - indexes that the models declare (`index=True`) were never created: on audit_logs, crm_sync_logs, lead_scores and raw_events;
  - model_registry.version had a plain index next to its unique constraint, which already provides one: the plain index is dropped.

(The models were corrected rather than the database where the database was right: four boolean columns were declared as Integer, and two indexes that exist
were not declared. See `tests/test_schema.py`, which fails if the models and the migrations drift apart again.)

Revision ID: 003
Revises: 002
"""

from collections.abc import Sequence

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = [
    ("ix_audit_logs_action", "audit_logs", ["action"]),
    ("ix_audit_logs_created_at", "audit_logs", ["created_at"]),
    ("ix_crm_sync_logs_company_id", "crm_sync_logs", ["company_id"]),
    ("ix_crm_sync_logs_contact_id", "crm_sync_logs", ["contact_id"]),
    ("ix_crm_sync_logs_crm_system", "crm_sync_logs", ["crm_system"]),
    ("ix_crm_sync_logs_job_id", "crm_sync_logs", ["job_id"]),
    ("ix_lead_scores_company_id", "lead_scores", ["company_id"]),
    ("ix_lead_scores_scoring_run_id", "lead_scores", ["scoring_run_id"]),
    ("ix_raw_events_event_time", "raw_events", ["event_time"]),
    ("ix_raw_events_job_id", "raw_events", ["job_id"]),
    ("ix_raw_events_trace_id", "raw_events", ["trace_id"]),
]


def upgrade() -> None:
    op.execute("DELETE FROM webhook_delivery_logs WHERE webhook_id NOT IN (SELECT id FROM webhooks)")
    op.create_foreign_key(
        "fk_webhook_delivery_logs_webhook_id",
        "webhook_delivery_logs",
        "webhooks",
        ["webhook_id"],
        ["id"],
        ondelete="CASCADE",
    )
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)
    op.drop_index("ix_model_registry_version", table_name="model_registry")


def downgrade() -> None:
    op.create_index("ix_model_registry_version", "model_registry", ["version"])
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
    op.drop_constraint("fk_webhook_delivery_logs_webhook_id", "webhook_delivery_logs", type_="foreignkey")
