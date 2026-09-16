'''Alembic migration for creating identity_run_status table'''

from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as psql

# revision identifiers, used by Alembic.
revision = '022_create_identity_run_status'
down_revision = '021_add_lease_columns_to_checkpoint'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'identity_run_status',
        sa.Column('batch_id', psql.UUID(as_uuid=True), nullable=False),
        sa.Column('identity_run_id', psql.UUID(as_uuid=True), nullable=False),
        sa.Column('run_status', sa.Text, nullable=False),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('batch_id', 'identity_run_id', name='pk_identity_run_status')
    )
    # Add CHECK constraint for completed_at semantics
    op.create_check_constraint(
        'chk_identity_run_status_completed',
        'identity_run_status',
        "(run_status = 'SUCCESS' AND completed_at IS NOT NULL) OR (run_status = 'FAILURE' AND completed_at IS NULL)"
    )

def downgrade():
    op.drop_table('identity_run_status')
