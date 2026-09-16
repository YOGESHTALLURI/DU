"""Wave 2 Slice 1: Production DQ Execution Engine & Pre-Ingestion Schema Drift Detection (CF-V2-E5-04, CF-V2-E7-05)

Revision ID: 009_wave2_slice1_drift_and_dq_results
Revises: 008_slice7_business_glossary
Create Date: 2026-09-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '009_slice1_drift_dq'
down_revision: Union[str, None] = '008_slice7_business_glossary'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New audit actions
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'schema.drift_detected'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'schema.drift_acknowledged'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'rule.production_executed'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'rule.batch_aborted'")

    # 2. New enums
    op.execute("DO $$ BEGIN CREATE TYPE drift_severity_enum AS ENUM ('NONE', 'NON_BREAKING', 'BREAKING'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE drift_status_enum AS ENUM ('DETECTED', 'ACKNOWLEDGED', 'RESOLVED'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE dq_action_taken_enum AS ENUM ('PASSED', 'LOGGED_INFO', 'LOGGED_WARNING', 'QUARANTINED_ROWS', 'BATCH_ABORTED'); EXCEPTION WHEN duplicate_object THEN null; END $$;")

    # 3. Create schema_drift_reports table
    op.create_table(
        'schema_drift_reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('feed_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feeds.id', ondelete='CASCADE'), nullable=False),
        sa.Column('expected_schema_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('schema_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('drift_severity', postgresql.ENUM('NONE', 'NON_BREAKING', 'BREAKING', name='drift_severity_enum', create_type=False), nullable=False),
        sa.Column('missing_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('unexpected_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('type_mismatches', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('detected_delimiter', sa.String(length=10), nullable=True),
        sa.Column('status', postgresql.ENUM('DETECTED', 'ACKNOWLEDGED', 'RESOLVED', name='drift_status_enum', create_type=False), nullable=False, server_default='DETECTED'),
        sa.Column('acknowledged_by', sa.String(length=255), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledgement_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.String(length=255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by', sa.String(length=255), nullable=False),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    )
    op.create_index('ix_schema_drift_reports_batch_id', 'schema_drift_reports', ['batch_id'])
    op.create_index('ix_schema_drift_reports_feed_id', 'schema_drift_reports', ['feed_id'])
    op.create_index('ix_schema_drift_reports_severity', 'schema_drift_reports', ['drift_severity'])

    # 4. Create dq_results table
    op.create_table(
        'dq_results',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('stage_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('batch_stages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('rule_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('rule_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('total_rows_evaluated', sa.Integer(), nullable=False),
        sa.Column('passed_rows', sa.Integer(), nullable=False),
        sa.Column('failed_rows', sa.Integer(), nullable=False),
        sa.Column('pass_rate', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('action_taken', postgresql.ENUM('PASSED', 'LOGGED_INFO', 'LOGGED_WARNING', 'QUARANTINED_ROWS', 'BATCH_ABORTED', name='dq_action_taken_enum', create_type=False), nullable=False),
        sa.Column('execution_duration_ms', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.String(length=255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by', sa.String(length=255), nullable=False),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        sa.UniqueConstraint('batch_id', 'rule_version_id', name='uq_dq_results_batch_rule'),
    )
    op.create_index('ix_dq_results_batch_id', 'dq_results', ['batch_id'])
    op.create_index('ix_dq_results_rule_version_id', 'dq_results', ['rule_version_id'])
    op.create_index('ix_dq_results_action_taken', 'dq_results', ['action_taken'])


def downgrade() -> None:
    op.drop_table('dq_results')
    op.drop_table('schema_drift_reports')
    op.execute("DROP TYPE IF EXISTS dq_action_taken_enum;")
    op.execute("DROP TYPE IF EXISTS drift_status_enum;")
    op.execute("DROP TYPE IF EXISTS drift_severity_enum;")
