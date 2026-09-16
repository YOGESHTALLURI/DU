"""Wave 2 Slice 4: Failure Fingerprinting, Recovery Playbooks & Self-Explaining Alerts (CF-V2-E12-04, CF-V2-E12-05)

Revision ID: 012_slice4_fingerprints_playbooks_alerts
Revises: 011_slice3_recovery_governance
Create Date: 2026-09-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '012_slice4_incidents_alerts'
down_revision: Union[str, None] = '011_slice3_recovery_governance'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New audit actions
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.fingerprint_created'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.alert_created'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.alert_acknowledged'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.alert_resolved'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.alert_reopened'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.playbook_created'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.playbook_updated'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.playbook_approved'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'ops.playbook_deprecated'")

    # 2. New enums
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE failure_category_enum AS ENUM (
                'SCHEMA_DRIFT',
                'DATA_QUALITY',
                'STAGE_EXECUTION',
                'RECONCILIATION',
                'DEPENDENCY_GATE',
                'NETWORK_STORAGE',
                'SYSTEM_TIMEOUT'
            );
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE alert_status_enum AS ENUM (
                'OPEN',
                'ACKNOWLEDGED',
                'RECOVERY_IN_PROGRESS',
                'RESOLVED',
                'REOPENED'
            );
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE alert_severity_enum AS ENUM (
                'CRITICAL',
                'WARNING',
                'INFO'
            );
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE playbook_status_enum AS ENUM (
                'DRAFT',
                'APPROVED',
                'DEPRECATED'
            );
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)

    # 3. Create failure_fingerprints table
    op.create_table(
        'failure_fingerprints',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('category', postgresql.ENUM('SCHEMA_DRIFT', 'DATA_QUALITY', 'STAGE_EXECUTION', 'RECONCILIATION', 'DEPENDENCY_GATE', 'NETWORK_STORAGE', 'SYSTEM_TIMEOUT', name='failure_category_enum', create_type=False), nullable=False),
        sa.Column('failure_stage', sa.String(50), nullable=True),
        sa.Column('root_cause_pattern', sa.String(255), nullable=False),
        sa.Column('canonical_signature', sa.Text(), nullable=False),
        sa.Column('fingerprint_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('total_occurrences', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_by', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.create_index('ix_failure_fingerprints_category', 'failure_fingerprints', ['category'])
    op.create_index('ix_failure_fingerprints_hash', 'failure_fingerprints', ['fingerprint_hash'])

    # 4. Create recovery_playbooks table
    op.create_table(
        'recovery_playbooks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('category', postgresql.ENUM('SCHEMA_DRIFT', 'DATA_QUALITY', 'STAGE_EXECUTION', 'RECONCILIATION', 'DEPENDENCY_GATE', 'NETWORK_STORAGE', 'SYSTEM_TIMEOUT', name='failure_category_enum', create_type=False), nullable=False),
        sa.Column('playbook_code', sa.String(64), nullable=False, unique=True),
        sa.Column('current_version_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('status', postgresql.ENUM('DRAFT', 'APPROVED', 'DEPRECATED', name='playbook_status_enum', create_type=False), nullable=False, server_default='DRAFT'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_by', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.create_index('ix_recovery_playbooks_category', 'recovery_playbooks', ['category'])
    op.create_index('ix_recovery_playbooks_code', 'recovery_playbooks', ['playbook_code'])

    # 5. Create recovery_playbook_versions table
    op.create_table(
        'recovery_playbook_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('playbook_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('recovery_playbooks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('explanation_template', sa.Text(), nullable=False),
        sa.Column('suggested_action_type', postgresql.ENUM('RESTART_BATCH', 'RETRIGGER_BATCH', 'REPROCESS_QUARANTINE', 'BULK_REPROCESS_QUARANTINE', 'DISCARD_QUARANTINE', 'PAUSE_SCHEDULE', 'RESUME_SCHEDULE', name='action_type_enum', create_type=False), nullable=True),
        sa.Column('action_parameters_template', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('manual_steps_markdown', sa.Text(), nullable=False, server_default=''),
        sa.Column('prerequisites', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('risk_assessment', sa.Text(), nullable=False, server_default=''),
        sa.Column('approved_by', sa.String(255), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', postgresql.ENUM('DRAFT', 'APPROVED', 'DEPRECATED', name='playbook_status_enum', create_type=False), nullable=False, server_default='DRAFT'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_by', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.UniqueConstraint('playbook_id', 'version_number', name='uq_playbook_version'),
    )
    op.create_index('ix_recovery_playbook_versions_playbook_id', 'recovery_playbook_versions', ['playbook_id'])

    # Add FK for current_version_id in recovery_playbooks
    op.create_foreign_key(
        'fk_recovery_playbooks_current_version',
        'recovery_playbooks',
        'recovery_playbook_versions',
        ['current_version_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # 6. Create fingerprint_playbook_bindings table
    op.create_table(
        'fingerprint_playbook_bindings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('fingerprint_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('failure_fingerprints.id', ondelete='CASCADE'), nullable=False),
        sa.Column('playbook_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('recovery_playbooks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_by', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.UniqueConstraint('fingerprint_id', 'playbook_id', name='uq_fingerprint_playbook_binding'),
    )

    # 7. Create operational_alerts table
    op.create_table(
        'operational_alerts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('feed_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feeds.id', ondelete='CASCADE'), nullable=False),
        sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('batches.id', ondelete='SET NULL'), nullable=True),
        sa.Column('failure_fingerprint_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('failure_fingerprints.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('recommended_playbook_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('recovery_playbook_versions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('severity', postgresql.ENUM('CRITICAL', 'WARNING', 'INFO', name='alert_severity_enum', create_type=False), nullable=False),
        sa.Column('status', postgresql.ENUM('OPEN', 'ACKNOWLEDGED', 'RECOVERY_IN_PROGRESS', 'RESOLVED', 'REOPENED', name='alert_status_enum', create_type=False), nullable=False, server_default='OPEN'),
        sa.Column('occurrence_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('first_occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_by', sa.String(255), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by', sa.String(255), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_by', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.create_index('ix_operational_alerts_feed_id', 'operational_alerts', ['feed_id'])
    op.create_index('ix_operational_alerts_status', 'operational_alerts', ['status'])
    op.create_index('ix_operational_alerts_severity', 'operational_alerts', ['severity'])
    op.create_index('ix_operational_alerts_fingerprint', 'operational_alerts', ['failure_fingerprint_id'])

    # Partial unique index for active alert deduplication
    op.execute("""
        CREATE UNIQUE INDEX uq_active_feed_fingerprint_alert
        ON operational_alerts (feed_id, failure_fingerprint_id)
        WHERE status IN ('OPEN', 'ACKNOWLEDGED', 'RECOVERY_IN_PROGRESS', 'REOPENED');
    """)

    # 8. Create alert_occurrences table
    op.create_table(
        'alert_occurrences',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('alert_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('operational_alerts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('batches.id', ondelete='SET NULL'), nullable=True),
        sa.Column('stage', sa.String(50), nullable=True),
        sa.Column('error_context', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_by', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.create_index('ix_alert_occurrences_alert_id', 'alert_occurrences', ['alert_id'])


def downgrade() -> None:
    op.drop_table('alert_occurrences')
    op.execute("DROP INDEX IF EXISTS uq_active_feed_fingerprint_alert")
    op.drop_table('operational_alerts')
    op.drop_table('fingerprint_playbook_bindings')
    op.drop_constraint('fk_recovery_playbooks_current_version', 'recovery_playbooks', type_='foreignkey')
    op.drop_table('recovery_playbook_versions')
    op.drop_table('recovery_playbooks')
    op.drop_table('failure_fingerprints')
    op.execute("DROP TYPE IF EXISTS playbook_status_enum")
    op.execute("DROP TYPE IF EXISTS alert_severity_enum")
    op.execute("DROP TYPE IF EXISTS alert_status_enum")
    op.execute("DROP TYPE IF EXISTS failure_category_enum")
