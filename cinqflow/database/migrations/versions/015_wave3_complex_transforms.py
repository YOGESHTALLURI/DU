"""Wave 3 Slice 1: Complex Healthcare Formats and Structural Transforms
(CF-V3-E5-05, CF-V3-E6-05)

Revision ID: 015_wave3_complex_transforms
Revises: 014_slice5_scopes_and_indexes
Create Date: 2026-09-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '015_wave3_complex_transforms'
down_revision: Union[str, None] = '014_slice5_scopes_and_indexes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extend transform_type_enum with structural transform types for complex healthcare formats
    op.execute("ALTER TYPE transform_type_enum ADD VALUE IF NOT EXISTS 'EXPLODE'")
    op.execute("ALTER TYPE transform_type_enum ADD VALUE IF NOT EXISTS 'FLATTEN'")
    op.execute("ALTER TYPE transform_type_enum ADD VALUE IF NOT EXISTS 'PATH_EXTRACT'")
    op.execute("ALTER TYPE transform_type_enum ADD VALUE IF NOT EXISTS 'ARRAY_MAP'")
    op.execute("ALTER TYPE transform_type_enum ADD VALUE IF NOT EXISTS 'UNNEST'")


def downgrade() -> None:
    # PostgreSQL ENUM values cannot be removed without rebuilding the type.
    pass
