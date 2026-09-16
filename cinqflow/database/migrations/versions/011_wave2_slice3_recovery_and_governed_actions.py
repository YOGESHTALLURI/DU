"""Wave 2 Slice 3: Recovery Operations & Governed Action Surface (CF-V2-E8-04, CF-V2-E12-03)

Revision ID: 011_slice3_recovery_governance
Revises: 010_slice2_ops
Create Date: 2026-09-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '011_slice3_recovery_governance'
down_revision: Union[str, None] = '010_slice2_ops'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New audit actions
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.action_requested'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.action_approved'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.action_rejected'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.action_executed'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.action_failed'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.quarantine_reprocessed'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.quarantine_discarded'")

    # 2. Quarantine status enum & columns
    op.execute("DO $$ BEGIN CREATE TYPE quarantine_status_enum AS ENUM ('QUARANTINED', 'REPROCESSED', 'DISCARDED'); EXCEPTION WHEN duplicate_object THEN null; END $$;")

    op.add_column(
        'quarantine_records',
        sa.Column('status', postgresql.ENUM('QUARANTINED', 'REPROCESSED', 'DISCARDED', name='quarantine_status_enum', create_type=False), nullable=False, server_default='QUARANTINED')
    )
    op.add_column(
        'quarantine_records',
        sa.Column('resolution_batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('batches.id', ondelete='SET NULL'), nullable=True)
    )
    op.add_column(
        'quarantine_records',
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'quarantine_records',
        sa.Column('resolved_by', sa.String(length=255), nullable=True)
    )
    op.add_column(
        'quarantine_records',
        sa.Column('resolution_notes', sa.Text(), nullable=True)
    )
    op.create_index('ix_quarantine_status', 'quarantine_records', ['status'])
    op.create_index('ix_quarantine_records_resolution_batch_id', 'quarantine_records', ['resolution_batch_id'])

    # 2b. Add parent_batch_id lineage to batches
    op.add_column(
        'batches',
        sa.Column('parent_batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('batches.id', ondelete='SET NULL'), nullable=True)
    )
    op.create_index('ix_batches_parent_batch_id', 'batches', ['parent_batch_id'])

    # 3. Governed action enums & table
    op.execute("""DO $$ BEGIN CREATE TYPE action_type_enum AS ENUM (
        'RESTART_BATCH',
        'RETRIGGER_BATCH',
        'REPROCESS_QUARANTINE',
        'BULK_REPROCESS_QUARANTINE',
        'DISCARD_QUARANTINE',
        'PAUSE_SCHEDULE',
        'RESUME_SCHEDULE'
    ); EXCEPTION WHEN duplicate_object THEN null; END $$;""")
    
    op.execute("DO $$ BEGIN CREATE TYPE action_risk_level_enum AS ENUM ('STANDARD', 'HIGH_RISK'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    
    op.execute("""DO $$ BEGIN CREATE TYPE action_status_enum AS ENUM (
        'PENDING_APPROVAL',
        'APPROVED',
        'EXECUTING',
        'COMPLETED',
        'REJECTED',
        'FAILED'
    ); EXCEPTION WHEN duplicate_object THEN null; END $$;""")

    op.create_table(
        'operational_action_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('action_type', postgresql.ENUM('RESTART_BATCH', 'RETRIGGER_BATCH', 'REPROCESS_QUARANTINE', 'BULK_REPROCESS_QUARANTINE', 'DISCARD_QUARANTINE', 'PAUSE_SCHEDULE', 'RESUME_SCHEDULE', name='action_type_enum', create_type=False), nullable=False),
        sa.Column('target_type', sa.String(length=50), nullable=False),
        sa.Column('target_id', sa.String(length=255), nullable=False),
        sa.Column('parameters', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('idempotency_key', sa.String(length=64), nullable=True, unique=True),
        sa.Column('risk_level', postgresql.ENUM('STANDARD', 'HIGH_RISK', name='action_risk_level_enum', create_type=False), nullable=False, server_default='STANDARD'),
        sa.Column('status', postgresql.ENUM('PENDING_APPROVAL', 'APPROVED', 'EXECUTING', 'COMPLETED', 'REJECTED', 'FAILED', name='action_status_enum', create_type=False), nullable=False, server_default='PENDING_APPROVAL'),
        sa.Column('requested_by', sa.String(length=255), nullable=False),
        sa.Column('requested_by_email', sa.String(length=255), nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('reviewed_by', sa.String(length=255), nullable=True),
        sa.Column('reviewed_by_email', sa.String(length=255), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decision_notes', sa.Text(), nullable=True),
        sa.Column('execution_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        # AuditMixin columns
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_by', sa.String(length=255), nullable=False, server_default='system'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_by', sa.String(length=255), nullable=False, server_default='system'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )

    op.create_index('ix_ops_action_status_risk', 'operational_action_requests', ['status', 'risk_level'])
    op.create_index('ix_ops_action_target', 'operational_action_requests', ['target_type', 'target_id'])
    op.create_index('ix_ops_action_requester', 'operational_action_requests', ['requested_by', 'action_type'])


def downgrade() -> None:
    op.drop_table('operational_action_requests')
    op.drop_index('ix_quarantine_records_resolution_batch_id', table_name='quarantine_records')
    op.drop_index('ix_quarantine_status', table_name='quarantine_records')
    op.drop_column('quarantine_records', 'resolution_notes')
    op.drop_column('quarantine_records', 'resolved_by')
    op.drop_column('quarantine_records', 'resolved_at')
    op.drop_column('quarantine_records', 'resolution_batch_id')
    op.drop_column('quarantine_records', 'status')
    op.execute("DROP TYPE IF EXISTS quarantine_status_enum")
    op.execute("DROP TYPE IF EXISTS action_status_enum")
    op.execute("DROP TYPE IF EXISTS action_risk_level_enum")
    op.execute("DROP TYPE IF EXISTS action_type_enum")
