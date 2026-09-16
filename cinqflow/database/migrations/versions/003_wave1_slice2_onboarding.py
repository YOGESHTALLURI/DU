"""Wave 1 Slice 2: Feed Lifecycle, Cloning and Onboarding Sessions

Revision ID: 003_wave1_slice2_onboarding
Revises: 002_wave1_profiling_and_schemas
Create Date: 2026-09-04
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '003_wave1_slice2_onboarding'
down_revision: Union[str, None] = '002_wave1_profiling_and_schemas'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New audit actions
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'feed.cloned'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'onboarding.started'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'onboarding.step_completed'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'onboarding.completed'")

    # 2. Add columns to feeds table
    op.add_column('feeds', sa.Column('source_system', sa.String(255), nullable=True))
    op.add_column('feeds', sa.Column('data_owner', sa.String(255), nullable=True))
    op.add_column('feeds', sa.Column('sla_expectation', sa.String(255), nullable=True))
    op.add_column('feeds', sa.Column('cloned_from_feed_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feeds.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_feeds_source_system', 'feeds', ['source_system'])
    op.create_index('ix_feeds_cloned_from_feed_id', 'feeds', ['cloned_from_feed_id'])

    # 3. New enum for onboarding_status_enum
    op.execute("CREATE TYPE onboarding_status_enum AS ENUM ('IN_PROGRESS', 'COMPLETED', 'ABANDONED')")

    # 4. Create onboarding_sessions table
    op.create_table(
        'onboarding_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('feed_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feeds.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('current_step', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('completed_steps', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('sample_file_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sample_files.id', ondelete='SET NULL'), nullable=True),
        sa.Column('profiling_run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('profiling_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('schema_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('schemas.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', postgresql.ENUM('IN_PROGRESS', 'COMPLETED', 'ABANDONED', name='onboarding_status_enum', create_type=False), nullable=False, server_default='IN_PROGRESS'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_by', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.create_index('ix_onboarding_sessions_feed_id', 'onboarding_sessions', ['feed_id'])
    op.create_index('ix_onboarding_sessions_status', 'onboarding_sessions', ['status'])


def downgrade() -> None:
    op.drop_table('onboarding_sessions')
    op.execute('DROP TYPE IF EXISTS onboarding_status_enum')
    op.drop_index('ix_feeds_cloned_from_feed_id', table_name='feeds')
    op.drop_index('ix_feeds_source_system', table_name='feeds')
    op.drop_column('feeds', 'cloned_from_feed_id')
    op.drop_column('feeds', 'sla_expectation')
    op.drop_column('feeds', 'data_owner')
    op.drop_column('feeds', 'source_system')
