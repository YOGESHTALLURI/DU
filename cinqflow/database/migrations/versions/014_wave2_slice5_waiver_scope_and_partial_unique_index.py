"""Wave 2 Slice 5: Enhanced Waiver Scopes, Partial Unique Index, and Certification Creation Safety
(CF-V2-E13-03, CF-V2-E13-04)

Revision ID: 014_slice5_scopes_and_indexes
Revises: 013_slice5_governance
Create Date: 2026-09-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '014_slice5_scopes_and_indexes'
down_revision: Union[str, None] = '013_slice5_governance'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add scope fields to operational_waivers
    op.add_column(
        'operational_waivers',
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()'))
    )
    op.add_column(
        'operational_waivers',
        sa.Column('range_start_batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('batches.id', ondelete='SET NULL'), nullable=True)
    )
    op.add_column(
        'operational_waivers',
        sa.Column('range_end_batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('batches.id', ondelete='SET NULL'), nullable=True)
    )
    op.add_column(
        'operational_waivers',
        sa.Column('target_batch_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )

    # 2. Add PostgreSQL partial unique index: at most one active (PENDING_APPROVAL or APPROVED) waiver per variance
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_waiver_active_variance
        ON operational_waivers (variance_id)
        WHERE status IN ('PENDING_APPROVAL', 'APPROVED');
    """)

    # 3. Remove server_default on batch_data_certifications.status so rows cannot be created with default CERTIFIED
    op.alter_column(
        'batch_data_certifications',
        'status',
        server_default=None
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_waiver_active_variance;")
    op.drop_column('operational_waivers', 'target_batch_ids')
    op.drop_column('operational_waivers', 'range_end_batch_id')
    op.drop_column('operational_waivers', 'range_start_batch_id')
    op.drop_column('operational_waivers', 'valid_from')
    op.alter_column(
        'batch_data_certifications',
        'status',
        server_default='CERTIFIED'
    )
