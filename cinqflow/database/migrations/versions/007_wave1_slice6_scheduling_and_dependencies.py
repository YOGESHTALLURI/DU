"""Wave 1 Slice 6: Scheduling, Dependencies and Downstream Protection (CF-V1-E8-03)

Revision ID: 007_slice6_scheduling_dependencies
Revises: 006_slice5_review_activate
Create Date: 2026-09-05
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '007_slice6_sched_dep'
down_revision: Union[str, None] = '006_slice5_review_activate'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New audit actions
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'schedule.created'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'schedule.updated'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'schedule.paused'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'schedule.resumed'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'schedule.disabled'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'schedule.enabled'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'dependency.created'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'dependency.deleted'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'dependency.cycle_rejected'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'dependency.gate_blocked'")

    # 2. New enums
    op.execute("DO $$ BEGIN CREATE TYPE schedule_status_enum AS ENUM ('ACTIVE', 'PAUSED', 'DISABLED'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE dependency_type_enum AS ENUM ('HARD', 'SOFT'); EXCEPTION WHEN duplicate_object THEN null; END $$;")

    # 3. Create feed_schedules table
    op.create_table(
        'feed_schedules',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('feed_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feeds.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('schedule_expression', sa.String(length=100), nullable=False, server_default='0 0 * * *'),
        sa.Column('timezone', sa.String(length=50), nullable=False, server_default='UTC'),
        sa.Column('status', postgresql.ENUM('ACTIVE', 'PAUSED', 'DISABLED', name='schedule_status_enum', create_type=False), nullable=False, server_default='ACTIVE'),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('catchup', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('created_by', sa.String(length=255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_by', sa.String(length=255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.create_index('ix_feed_schedules_feed_id', 'feed_schedules', ['feed_id'])
    op.create_index('ix_feed_schedules_status', 'feed_schedules', ['status'])

    # 4. Create feed_dependencies table
    op.create_table(
        'feed_dependencies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('downstream_feed_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feeds.id', ondelete='CASCADE'), nullable=False),
        sa.Column('upstream_feed_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feeds.id', ondelete='CASCADE'), nullable=False),
        sa.Column('dependency_type', postgresql.ENUM('HARD', 'SOFT', name='dependency_type_enum', create_type=False), nullable=False, server_default='HARD'),
        sa.Column('max_lag_hours', sa.Integer(), nullable=False, server_default='24'),
        sa.Column('block_on_upstream_failure', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('block_on_reject_file', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('block_on_unbalanced_reconciliation', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('max_quarantine_rate_pct', sa.Float(), nullable=True, server_default='5.0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('created_by', sa.String(length=255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_by', sa.String(length=255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.CheckConstraint('downstream_feed_id != upstream_feed_id', name='chk_no_self_dependency'),
        sa.UniqueConstraint('downstream_feed_id', 'upstream_feed_id', name='uq_downstream_upstream'),
    )
    op.create_index('ix_feed_dependencies_downstream', 'feed_dependencies', ['downstream_feed_id'])
    op.create_index('ix_feed_dependencies_upstream', 'feed_dependencies', ['upstream_feed_id'])


def downgrade() -> None:
    op.drop_table('feed_dependencies')
    op.drop_table('feed_schedules')
    op.execute("DROP TYPE IF EXISTS dependency_type_enum")
    op.execute("DROP TYPE IF EXISTS schedule_status_enum")
