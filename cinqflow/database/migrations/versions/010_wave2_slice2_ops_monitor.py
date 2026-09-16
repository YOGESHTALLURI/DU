"""Wave 2 Slice 2: Operations Control Center, File-Arrival Board & Batch/Stage Monitor (CF-V2-E12-01, CF-V2-E12-02)

Revision ID: 010_slice2_ops
Revises: 009_slice1_drift_dq
Create Date: 2026-09-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '010_slice2_ops'
down_revision: Union[str, None] = '009_slice1_drift_dq'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New audit actions
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.dashboard_viewed'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.arrivals_evaluated'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.sla_breached'")

    # 2. Add SLA configuration columns to feed_schedules
    op.add_column(
        'feed_schedules',
        sa.Column('sla_grace_minutes', sa.Integer(), nullable=False, server_default='60')
    )
    op.add_column(
        'feed_schedules',
        sa.Column('lead_window_minutes', sa.Integer(), nullable=False, server_default='120')
    )

    # 3. Create high-performance indexes
    op.execute("CREATE INDEX IF NOT EXISTS ix_batches_created_at_desc ON batches (created_at DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_batches_status_created_at ON batches (status, created_at DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_batches_feed_created_at ON batches (feed_id, created_at DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_batch_stages_batch_order ON batch_stages (batch_id, stage_order);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_input_registry_feed_detected ON input_registry (feed_id, detected_at DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_dq_results_batch_id ON dq_results (batch_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_schema_drift_batch_id ON schema_drift_reports (batch_id);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_schema_drift_batch_id;")
    op.execute("DROP INDEX IF EXISTS ix_dq_results_batch_id;")
    op.execute("DROP INDEX IF EXISTS ix_input_registry_feed_detected;")
    op.execute("DROP INDEX IF EXISTS ix_batch_stages_batch_order;")
    op.execute("DROP INDEX IF EXISTS ix_batches_feed_created_at;")
    op.execute("DROP INDEX IF EXISTS ix_batches_status_created_at;")
    op.execute("DROP INDEX IF EXISTS ix_batches_created_at_desc;")

    op.drop_column('feed_schedules', 'lead_window_minutes')
    op.drop_column('feed_schedules', 'sla_grace_minutes')
