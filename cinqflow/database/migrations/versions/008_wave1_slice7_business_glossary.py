"""Wave 1 Slice 7: Enterprise Business Glossary Service & Canonical Semantics (CF-V1-E14-01)

Revision ID: 008_slice7_business_glossary
Revises: 007_slice6_sched_dep
Create Date: 2026-09-05
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '008_slice7_business_glossary'
down_revision: Union[str, None] = '007_slice6_sched_dep'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New audit actions
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'glossary.term_created'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'glossary.term_updated'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'glossary.term_approved'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'glossary.term_deprecated'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'glossary.term_deleted'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'glossary.field_linked'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'glossary.field_unlinked'")

    # 2. New enums
    op.execute("DO $$ BEGIN CREATE TYPE glossary_term_status_enum AS ENUM ('DRAFT', 'APPROVED', 'DEPRECATED'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE glossary_phi_classification_enum AS ENUM ('NONE', 'POTENTIAL_PHI', 'CONFIRMED_PHI'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE glossary_code_set_enum AS ENUM ('NONE', 'ICD_10', 'CPT', 'HCPCS', 'LOINC', 'SNOMED_CT', 'NDC', 'NPI'); EXCEPTION WHEN duplicate_object THEN null; END $$;")

    # 3. Create glossary_terms table
    op.create_table(
        'glossary_terms',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('normalized_name', sa.String(length=255), nullable=False, unique=True),
        sa.Column('acronym', sa.String(length=50), nullable=True),
        sa.Column('synonyms', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('domain', sa.String(length=100), nullable=False),
        sa.Column('definition', sa.Text(), nullable=False),
        sa.Column('clinical_context', sa.Text(), nullable=True),
        sa.Column('data_steward', sa.String(length=255), nullable=True),
        sa.Column('status', postgresql.ENUM('DRAFT', 'APPROVED', 'DEPRECATED', name='glossary_term_status_enum', create_type=False), nullable=False, server_default='DRAFT'),
        sa.Column('phi_classification', postgresql.ENUM('NONE', 'POTENTIAL_PHI', 'CONFIRMED_PHI', name='glossary_phi_classification_enum', create_type=False), nullable=False, server_default='NONE'),
        sa.Column('code_set', postgresql.ENUM('NONE', 'ICD_10', 'CPT', 'HCPCS', 'LOINC', 'SNOMED_CT', 'NDC', 'NPI', name='glossary_code_set_enum', create_type=False), nullable=False, server_default='NONE'),
        sa.Column('deprecation_reason', sa.Text(), nullable=True),
        sa.Column('replaced_by_term_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('glossary_terms.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('created_by', sa.String(length=255), nullable=False, server_default='system'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('updated_by', sa.String(length=255), nullable=False, server_default='system'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.CheckConstraint("(status != 'DEPRECATED') OR (deprecation_reason IS NOT NULL AND length(trim(deprecation_reason)) > 0)", name='chk_term_deprecated_reason'),
    )
    op.create_index('ix_glossary_terms_name', 'glossary_terms', ['name'])
    op.create_index('ix_glossary_terms_domain', 'glossary_terms', ['domain'])
    op.create_index('ix_glossary_terms_status', 'glossary_terms', ['status'])
    op.create_index('ix_glossary_terms_phi', 'glossary_terms', ['phi_classification'])

    # 4. Create glossary_canonical_links table
    op.create_table(
        'glossary_canonical_links',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('glossary_term_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('glossary_terms.id', ondelete='CASCADE'), nullable=False),
        sa.Column('canonical_field_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('canonical_fields.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('created_by', sa.String(length=255), nullable=False, server_default='system'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('updated_by', sa.String(length=255), nullable=False, server_default='system'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.UniqueConstraint('glossary_term_id', 'canonical_field_id', name='uq_term_canonical_field'),
    )
    op.create_index('ix_glossary_link_term', 'glossary_canonical_links', ['glossary_term_id'])
    op.create_index('ix_glossary_link_field', 'glossary_canonical_links', ['canonical_field_id'])


def downgrade() -> None:
    op.drop_table('glossary_canonical_links')
    op.drop_table('glossary_terms')
    op.execute("DROP TYPE IF EXISTS glossary_code_set_enum")
    op.execute("DROP TYPE IF EXISTS glossary_phi_classification_enum")
    op.execute("DROP TYPE IF EXISTS glossary_term_status_enum")
