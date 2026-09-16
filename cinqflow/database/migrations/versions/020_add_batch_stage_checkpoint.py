'''Alembic migration for adding batch_stage_checkpoint table'''

from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as psql

# revision identifiers, used by Alembic.
revision = '020_add_batch_stage_checkpoint'
down_revision = '019_wave4_merge_split_event'
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")
    op.create_table(
        'batch_stage_checkpoint',
        sa.Column('execution_id', psql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('batch_id', psql.UUID(as_uuid=True), nullable=False),
        sa.Column('stage_name', sa.Text, nullable=False),
        sa.Column('checkpoint_key', sa.Text, nullable=False),
        sa.Column('checkpoint_value', sa.Text, nullable=False),
        sa.Column('execution_state', sa.Text, nullable=False),
        sa.Column('lease_token', psql.UUID(as_uuid=True), nullable=True),
        sa.Column('lease_expires_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    # No partial unique index on BOUND executions per requirements.

    op.create_table(
        'ods_operation_hashes',
        sa.Column('op_hash', sa.Text, nullable=False),
        sa.Column('batch_id', psql.UUID(as_uuid=True), nullable=False),
        sa.Column('cinq_id', psql.UUID(as_uuid=True), nullable=False),
        sa.Column('operation', sa.Text, nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('op_hash', name='ods_op_hash_uniq'),
    )


def downgrade():
    op.drop_table('ods_operation_hashes')
    op.drop_table('batch_stage_checkpoint')
