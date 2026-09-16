"""Wave 2 Slice 5: Governance — Variances, Waivers & Batch Data Certification (CF-V2-E13-03, CF-V2-E13-04)

Revision ID: 013_slice5_governance
Revises: 012_slice4_incidents_alerts
Create Date: 2026-09-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '013_slice5_governance'
down_revision: Union[str, None] = '012_slice4_incidents_alerts'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New audit actions
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.variance_created'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.variance_resolved'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.waiver_requested'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.waiver_approved'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.waiver_rejected'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.waiver_revoked'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.waiver_expired'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.batch_certified'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.certification_revoked'")

    # 2. New enums
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE variance_status_enum AS ENUM (
                'OPEN',
                'WAIVED',
                'RESOLVED'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE waiver_status_enum AS ENUM (
                'PENDING_APPROVAL',
                'APPROVED',
                'REJECTED',
                'EXPIRED',
                'REVOKED'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE waiver_scope_enum AS ENUM (
                'SINGLE_BATCH',
                'BATCH_RANGE',
                'TIME_BOUNDED'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE certification_status_enum AS ENUM (
                'CERTIFIED',
                'REVOKED',
                'SUPERSEDED'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # 3. Create operational_variances
    op.create_table(
        'operational_variances',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('feed_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feeds.id', ondelete='CASCADE'), nullable=False),
        sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('control_type', sa.String(50), nullable=False),
        sa.Column('control_id', sa.String(255), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False, server_default='WARNING'),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('telemetry_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('status', postgresql.ENUM('OPEN', 'WAIVED', 'RESOLVED', name='variance_status_enum', create_type=False), nullable=False, server_default='OPEN'),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('updated_by', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.create_index('ix_variances_feed_id', 'operational_variances', ['feed_id'])
    op.create_index('ix_variances_batch_id', 'operational_variances', ['batch_id'])
    op.create_index('ix_variances_status', 'operational_variances', ['status'])
    op.create_index('ix_variances_batch_control', 'operational_variances', ['batch_id', 'control_type', 'control_id'])
    op.create_index('ix_variances_feed_status', 'operational_variances', ['feed_id', 'status'])

    # 4. Create operational_waivers
    op.create_table(
        'operational_waivers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('variance_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('operational_variances.id', ondelete='CASCADE'), nullable=False),
        sa.Column('feed_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feeds.id', ondelete='CASCADE'), nullable=False),
        sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scope', postgresql.ENUM('SINGLE_BATCH', 'BATCH_RANGE', 'TIME_BOUNDED', name='waiver_scope_enum', create_type=False), nullable=False, server_default='SINGLE_BATCH'),
        sa.Column('affected_control_type', sa.String(50), nullable=False),
        sa.Column('affected_control_id', sa.String(255), nullable=False),
        sa.Column('business_justification', sa.Text(), nullable=False),
        sa.Column('risk_assessment', sa.Text(), nullable=False),
        sa.Column('mitigation_notes', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('max_batches', sa.Integer(), nullable=True),
        sa.Column('batches_applied_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', postgresql.ENUM('PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'EXPIRED', 'REVOKED', name='waiver_status_enum', create_type=False), nullable=False, server_default='PENDING_APPROVAL'),
        sa.Column('requested_by', sa.String(255), nullable=False),
        sa.Column('requested_by_email', sa.String(255), nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('reviewed_by', sa.String(255), nullable=True),
        sa.Column('reviewed_by_email', sa.String(255), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decision_notes', sa.Text(), nullable=True),
        sa.Column('revoked_by', sa.String(255), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revocation_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('updated_by', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.create_index('ix_waivers_variance_id', 'operational_waivers', ['variance_id'])
    op.create_index('ix_waivers_batch_id', 'operational_waivers', ['batch_id'])
    op.create_index('ix_waivers_feed_id', 'operational_waivers', ['feed_id'])
    op.create_index('ix_waivers_status', 'operational_waivers', ['status'])
    op.create_index('ix_waivers_batch_status', 'operational_waivers', ['batch_id', 'status'])
    op.create_index('ix_waivers_feed_expires', 'operational_waivers', ['feed_id', 'expires_at'])

    # 5. Create batch_data_certifications
    op.create_table(
        'batch_data_certifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('feed_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feeds.id', ondelete='CASCADE'), nullable=False),
        sa.Column('feed_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feed_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('status', postgresql.ENUM('CERTIFIED', 'REVOKED', 'SUPERSEDED', name='certification_status_enum', create_type=False), nullable=False, server_default='CERTIFIED'),
        sa.Column('certified_with_waivers', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('applied_waiver_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('input_file_fingerprint', sa.String(64), nullable=False),
        sa.Column('input_filename', sa.String(255), nullable=False),
        sa.Column('total_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('reconciliation_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('dq_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('evidence_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('evidence_hash', sa.String(64), nullable=False),
        sa.Column('certified_by', sa.String(255), nullable=False),
        sa.Column('certified_by_email', sa.String(255), nullable=True),
        sa.Column('certified_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('certification_notes', sa.Text(), nullable=True),
        sa.Column('revoked_by', sa.String(255), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revocation_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('updated_by', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.create_index('ix_certifications_batch_id', 'batch_data_certifications', ['batch_id'])
    op.create_index('ix_certifications_feed_id', 'batch_data_certifications', ['feed_id'])
    op.create_index('ix_certifications_status', 'batch_data_certifications', ['status'])
    op.create_index('ix_certifications_feed_batch', 'batch_data_certifications', ['feed_id', 'batch_id'])
    op.create_index('ix_certifications_fingerprint', 'batch_data_certifications', ['input_file_fingerprint'])


def downgrade() -> None:
    op.drop_table('batch_data_certifications')
    op.drop_table('operational_waivers')
    op.drop_table('operational_variances')
    op.execute("DROP TYPE IF EXISTS certification_status_enum")
    op.execute("DROP TYPE IF EXISTS waiver_scope_enum")
    op.execute("DROP TYPE IF EXISTS waiver_status_enum")
    op.execute("DROP TYPE IF EXISTS variance_status_enum")
