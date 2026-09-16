"""Wave 1 Slice 5: Review, Sandbox Evidence Pack & Governed Activation

Revision ID: 006_wave1_slice5_review_and_activate
Revises: 005_data_quality_rules
Create Date: 2026-09-05
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '006_slice5_review_activate'
down_revision: Union[str, None] = '005_data_quality_rules'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New audit actions
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'sandbox_test.started'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'sandbox_test.completed'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'sandbox_test.failed'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'approval.submitted'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'approval.approved'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'approval.rejected'")

    # 2. New enums
    op.execute("DO $$ BEGIN CREATE TYPE sandbox_run_status_enum AS ENUM ('RUNNING', 'SUCCESS', 'FAILED'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE approval_request_status_enum AS ENUM ('PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'CANCELLED'); EXCEPTION WHEN duplicate_object THEN null; END $$;")

    # 3. sandbox_test_runs table
    op.create_table(
        'sandbox_test_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('feed_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feeds.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sample_file_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sample_files.id', ondelete='CASCADE'), nullable=False),
        sa.Column('schema_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('schema_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('mapping_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mapping_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('status', postgresql.ENUM('RUNNING', 'SUCCESS', 'FAILED', name='sandbox_run_status_enum', create_type=False), nullable=False, server_default='RUNNING'),
        sa.Column('total_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('passed_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('quarantined_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('dropped_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('pass_rate', sa.Numeric(5, 2), nullable=False, server_default='0.00'),
        sa.Column('reconciliation_status', sa.String(50), nullable=False, server_default='PENDING'),
        sa.Column('rule_metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('canonical_sample_preview', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('has_reject_file_violation', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('execution_duration_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('executed_by', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.create_index('ix_sandbox_test_runs_feed_id', 'sandbox_test_runs', ['feed_id'])
    op.create_index('ix_sandbox_test_runs_status', 'sandbox_test_runs', ['status'])

    # 4. approval_requests table
    op.create_table(
        'approval_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('feed_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feeds.id', ondelete='CASCADE'), nullable=False),
        sa.Column('feed_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feed_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('schema_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('schema_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('mapping_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mapping_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('sandbox_test_run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sandbox_test_runs.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('status', postgresql.ENUM('PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'CANCELLED', name='approval_request_status_enum', create_type=False), nullable=False, server_default='PENDING_APPROVAL'),
        sa.Column('submitted_by', sa.String(255), nullable=False),
        sa.Column('submitted_by_email', sa.String(255), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('submission_notes', sa.Text(), nullable=True),
        sa.Column('reviewed_by', sa.String(255), nullable=True),
        sa.Column('reviewed_by_email', sa.String(255), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decision_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.create_index('ix_approval_requests_feed_id', 'approval_requests', ['feed_id'])
    op.create_index('ix_approval_requests_status', 'approval_requests', ['status'])

    # 5. feed_activation_records table
    op.create_table(
        'feed_activation_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('feed_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feeds.id', ondelete='CASCADE'), nullable=False),
        sa.Column('approval_request_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('approval_requests.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('feed_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feed_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('schema_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('schema_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('mapping_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mapping_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('rule_version_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('sandbox_test_run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sandbox_test_runs.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('activated_by', sa.String(255), nullable=False),
        sa.Column('activated_by_email', sa.String(255), nullable=True),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('activation_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.create_index('ix_feed_activation_records_feed_id', 'feed_activation_records', ['feed_id'])


def downgrade() -> None:
    op.drop_table('feed_activation_records')
    op.drop_table('approval_requests')
    op.drop_table('sandbox_test_runs')
    op.execute("DROP TYPE IF EXISTS approval_request_status_enum;")
    op.execute("DROP TYPE IF EXISTS sandbox_run_status_enum;")
