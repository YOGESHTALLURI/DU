'''Alembic migration for identity_merge_split_proposal'''

from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as psql

# revision identifiers, used by Alembic.
revision = '018_wave4_merge_split_proposal'
down_revision = '017_wave3_identity_foundation'
branch_labels = None
depends_on = None

def upgrade():
    # Create proposal table
    op.create_table(
        'identity_merge_split_proposal',
        sa.Column('proposal_id', psql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('source_cinq_id', psql.UUID(as_uuid=True), sa.ForeignKey('master_identities.cinq_id', ondelete='SET NULL'), nullable=True),
        sa.Column('target_cinq_id', psql.UUID(as_uuid=True), sa.ForeignKey('master_identities.cinq_id', ondelete='SET NULL'), nullable=True),
        sa.Column('operation_type', sa.String(length=10), nullable=False),  # MERGE or SPLIT
        sa.Column('client_key', sa.String(length=64), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False, server_default='PENDING_APPROVAL'),
        sa.Column('proposer_id', sa.String(length=255), nullable=False),
        sa.Column('approver_id', sa.String(length=255), nullable=True),
        sa.Column('expected_version', sa.Integer(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint("state IN ('PENDING_APPROVAL','APPROVED','REJECTED','EXECUTED','FAILED')", name='chk_proposal_state'),
        sa.CheckConstraint("operation_type IN ('MERGE','SPLIT')", name='chk_proposal_operation'),
    )
    # Partial unique index for active proposals
    op.create_index(
        'uq_active_proposal_client_key',
        'identity_merge_split_proposal',
        ['client_key', 'operation_type'],
        unique=True,
        postgresql_where=sa.text("state = 'PENDING_APPROVAL'")
    )

def downgrade():
    op.drop_index('uq_active_proposal_client_key', table_name='identity_merge_split_proposal')
    op.drop_table('identity_merge_split_proposal')
