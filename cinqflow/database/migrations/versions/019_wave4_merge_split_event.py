'''Alembic migration for identity_merge_split_event'''

from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as psql

# revision identifiers, used by Alembic.
revision = '019_wave4_merge_split_event'
down_revision = '018_wave4_merge_split_proposal'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'identity_merge_split_event',
        sa.Column('event_id', psql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('proposal_id', psql.UUID(as_uuid=True), sa.ForeignKey('identity_merge_split_proposal.proposal_id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.String(length=10), nullable=False),  # MERGE or SPLIT
        sa.Column('source_cinq_id', psql.UUID(as_uuid=True), sa.ForeignKey('master_identities.cinq_id', ondelete='SET NULL'), nullable=True),
        sa.Column('target_cinq_id', psql.UUID(as_uuid=True), sa.ForeignKey('master_identities.cinq_id', ondelete='SET NULL'), nullable=True),
        sa.Column('effective_from', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('effective_to', sa.DateTime(timezone=True), nullable=True),
        sa.Column('actor_uuid', psql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint("event_type IN ('MERGE','SPLIT')", name='chk_event_type'),
        sa.CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name='chk_event_temporal'),
    )
    op.create_index('ix_event_source', 'identity_merge_split_event', ['source_cinq_id'])
    op.create_index('ix_event_target', 'identity_merge_split_event', ['target_cinq_id'])

def downgrade():
    op.drop_index('ix_event_target', table_name='identity_merge_split_event')
    op.drop_index('ix_event_source', table_name='identity_merge_split_event')
    op.drop_table('identity_merge_split_event')
