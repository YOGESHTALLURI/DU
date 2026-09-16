'''Alembic migration for adding indexes to batch_stage_checkpoint lease columns'''

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '021_add_lease_columns_to_checkpoint'
down_revision = '020_add_batch_stage_checkpoint'
branch_labels = None
depends_on = None

def upgrade():
    op.create_index('ix_batch_stage_checkpoint_lease_token', 'batch_stage_checkpoint', ['lease_token'])
    op.create_index('ix_batch_stage_checkpoint_lease_expires_at', 'batch_stage_checkpoint', ['lease_expires_at'])

def downgrade():
    op.drop_index('ix_batch_stage_checkpoint_lease_expires_at', table_name='batch_stage_checkpoint')
    op.drop_index('ix_batch_stage_checkpoint_lease_token', table_name='batch_stage_checkpoint')
