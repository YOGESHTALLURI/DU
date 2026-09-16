"""Wave 1 Slice 4: Data Quality Rules Engine

Revision ID: 005_data_quality_rules
Revises: 004_canonical_and_mappings
Create Date: 2026-09-04
"""
from typing import Sequence, Union
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '005_data_quality_rules'
down_revision: Union[str, None] = '004_canonical_and_mappings'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New audit actions
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'rule.created'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'rule.draft_updated'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'rule.version_created'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'rule.published'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'rule.test_executed'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'rule.deleted'")

    # 2. New enums (Strictly 7 rule types, CUSTOM_SQL is completely excluded)
    op.execute("DO $$ BEGIN CREATE TYPE rule_version_status_enum AS ENUM ('DRAFT', 'PUBLISHED', 'SUPERSEDED', 'RETIRED'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE rule_type_enum AS ENUM ('NOT_NULL', 'RANGE', 'REGEX', 'ENUM', 'LENGTH', 'DATE_RANGE', 'CROSS_FIELD'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE rule_severity_enum AS ENUM ('INFO', 'WARNING', 'QUARANTINE', 'REJECT_FILE'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE test_run_status_enum AS ENUM ('COMPLETED', 'FAILED'); EXCEPTION WHEN duplicate_object THEN null; END $$;")

    # 3. data_quality_rules table
    op.create_table(
        'data_quality_rules',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('feed_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feeds.id', ondelete='CASCADE'), nullable=False),
        sa.Column('schema_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('schemas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    )
    op.create_index('ix_data_quality_rules_feed_id', 'data_quality_rules', ['feed_id'])
    op.create_index('ix_data_quality_rules_schema_id', 'data_quality_rules', ['schema_id'])
    op.create_index('ix_data_quality_rules_is_deleted', 'data_quality_rules', ['is_deleted'])
    op.create_index(
        'ix_dq_rule_feed_name_active',
        'data_quality_rules',
        ['feed_id', 'name'],
        unique=True,
        postgresql_where=sa.text('is_deleted = false')
    )

    # 4. rule_versions table
    op.create_table(
        'rule_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('rule_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('data_quality_rules.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('schema_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('schema_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('status', postgresql.ENUM('DRAFT', 'PUBLISHED', 'SUPERSEDED', 'RETIRED', name='rule_version_status_enum', create_type=False), server_default='DRAFT', nullable=False),
        sa.Column('rule_type', postgresql.ENUM('NOT_NULL', 'RANGE', 'REGEX', 'ENUM', 'LENGTH', 'DATE_RANGE', 'CROSS_FIELD', name='rule_type_enum', create_type=False), nullable=False),
        sa.Column('target_field', sa.String(255), nullable=False),
        sa.Column('severity', postgresql.ENUM('INFO', 'WARNING', 'QUARANTINE', 'REJECT_FILE', name='rule_severity_enum', create_type=False), server_default='QUARANTINE', nullable=False),
        sa.Column('rule_config', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('error_message_template', sa.String(500), nullable=True),
        sa.Column('change_notes', sa.Text(), nullable=True),
        sa.Column('compiled_spec', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('published_by', sa.String(255), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('needs_review', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        sa.UniqueConstraint('rule_id', 'version_number', name='uq_rule_version_number'),
    )
    op.create_index('ix_rule_versions_rule_id', 'rule_versions', ['rule_id'])
    op.create_index('ix_rule_versions_schema_version_id', 'rule_versions', ['schema_version_id'])
    op.create_index('ix_rule_versions_status', 'rule_versions', ['status'])

    # 5. rule_test_runs table
    op.create_table(
        'rule_test_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('rule_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('rule_versions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sample_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sample_files.id', ondelete='CASCADE'), nullable=False),
        sa.Column('total_rows', sa.Integer(), nullable=False),
        sa.Column('passed_rows', sa.Integer(), nullable=False),
        sa.Column('failed_rows', sa.Integer(), nullable=False),
        sa.Column('pass_rate', sa.Numeric(5, 2), nullable=False),
        sa.Column('status', postgresql.ENUM('COMPLETED', 'FAILED', name='test_run_status_enum', create_type=False), server_default='COMPLETED', nullable=False),
        sa.Column('error_detail', sa.Text(), nullable=True),
        sa.Column('failed_row_details', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('executed_by', sa.String(255), nullable=False),
        sa.Column('executed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    )
    op.create_index('ix_rule_test_runs_rule_version_id', 'rule_test_runs', ['rule_version_id'])
    op.create_index('ix_rule_test_runs_sample_id', 'rule_test_runs', ['sample_id'])


def downgrade() -> None:
    op.drop_table('rule_test_runs')
    op.drop_table('rule_versions')
    op.drop_table('data_quality_rules')
    op.execute("DROP TYPE IF EXISTS test_run_status_enum")
    op.execute("DROP TYPE IF EXISTS rule_severity_enum")
    op.execute("DROP TYPE IF EXISTS rule_type_enum")
    op.execute("DROP TYPE IF EXISTS rule_version_status_enum")
