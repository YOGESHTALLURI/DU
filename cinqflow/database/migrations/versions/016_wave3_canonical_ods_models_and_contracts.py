"""Wave 3 Slice 2: Canonical ODS Schema & Model Versioning
(CF-V3-E10-01, CF-V3-E10-02)

Revision ID: 016_wave3_canonical_ods_models
Revises: 015_wave3_complex_transforms
Create Date: 2026-09-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '016_wave3_canonical_ods_models'
down_revision: Union[str, None] = '015_wave3_complex_transforms'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 0. Add ODS audit actions to audit_action_enum
    for act in [
        'ods.model_version_created',
        'ods.model_version_published',
        'ods.consumer_registered',
        'ods.consumer_updated',
        'ods.consumer_deactivated',
        'ods.consumer_mismatch',
    ]:
        op.execute(f"ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS '{act}'")

    # 1. Create schemas for canonical internal storage and certified consumer access
    op.execute("CREATE SCHEMA IF NOT EXISTS internal_ods;")
    op.execute("CREATE SCHEMA IF NOT EXISTS ods_certified;")

    # 2. Create ods_model_versions table
    op.create_table(
        'ods_model_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('version_number', sa.Integer(), nullable=False, unique=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('domain', sa.String(50), nullable=False, server_default='clinical'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='DRAFT'),
        sa.Column('schema_definition', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_by', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('updated_by', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )

    # 3. Create immutability trigger for published ods_model_versions
    op.execute("""
    CREATE OR REPLACE FUNCTION fn_protect_published_ods_model_versions()
    RETURNS TRIGGER AS $$
    BEGIN
        IF OLD.status = 'PUBLISHED' THEN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Immutability Violation: Cannot delete published ODS model version %', OLD.version_number
                USING ERRCODE = 'check_violation';
            ELSIF TG_OP = 'UPDATE' THEN
                IF NEW.version_number != OLD.version_number 
                   OR NEW.schema_definition != OLD.schema_definition 
                   OR NEW.domain != OLD.domain THEN
                    RAISE EXCEPTION 'Immutability Violation: Cannot modify definition of published ODS model version %', OLD.version_number
                    USING ERRCODE = 'check_violation';
                END IF;
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_protect_published_ods_model_versions
    BEFORE UPDATE OR DELETE ON ods_model_versions
    FOR EACH ROW
    EXECUTE FUNCTION fn_protect_published_ods_model_versions();
    """)

    # 4. Create consumer_registrations table
    op.create_table(
        'consumer_registrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('consumer_name', sa.String(100), nullable=False, unique=True),
        sa.Column('consumer_type', sa.String(50), nullable=False),
        sa.Column('registered_ods_model_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('ods_model_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='ACTIVE'),
        sa.Column('db_role_name', sa.String(100), nullable=True),
        sa.Column('contact_email', sa.String(255), nullable=False),
        sa.Column('purpose', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('updated_by', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )

    # 5. Add ods_model_version_id to batches table
    op.add_column(
        'batches',
        sa.Column('ods_model_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('ods_model_versions.id', ondelete='RESTRICT'), nullable=True)
    )

    # 6. Create internal_ods.ods_members_v1 table (Grain: cinq_id, batch_id)
    op.create_table(
        'ods_members_v1',
        sa.Column('cinq_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ods_model_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('ods_model_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('first_name', sa.String(100), nullable=False),
        sa.Column('last_name', sa.String(100), nullable=False),
        sa.Column('date_of_birth', sa.Date(), nullable=False),
        sa.Column('gender', sa.String(20), nullable=False),
        sa.Column('address_line1', sa.String(255), nullable=True),
        sa.Column('city', sa.String(100), nullable=True),
        sa.Column('state', sa.String(2), nullable=True),
        sa.Column('postal_code', sa.String(10), nullable=True),
        sa.Column('survivorship_applied', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('updated_by', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.PrimaryKeyConstraint('cinq_id', 'batch_id', name='pk_ods_members_v1'),
        schema='internal_ods'
    )

    # 7. Create internal_ods.ods_claims_v1 table
    op.create_table(
        'ods_claims_v1',
        sa.Column('claim_id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('cinq_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ods_model_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('ods_model_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('claim_type', sa.String(50), nullable=False),
        sa.Column('total_charge_amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('claim_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('updated_by', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        schema='internal_ods'
    )

    # 8. Create internal_ods.ods_claim_lines_v1 table
    op.create_table(
        'ods_claim_lines_v1',
        sa.Column('claim_line_id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('claim_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('internal_ods.ods_claims_v1.claim_id', ondelete='CASCADE'), nullable=False),
        sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ods_model_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('ods_model_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('service_date', sa.Date(), nullable=False),
        sa.Column('procedure_code', sa.String(50), nullable=False),
        sa.Column('allowed_amount', sa.Numeric(14, 2), nullable=False, server_default='0.00'),
        sa.Column('paid_amount', sa.Numeric(14, 2), nullable=False, server_default='0.00'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('updated_by', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        schema='internal_ods'
    )

    # 9. Create internal_ods.ods_member_provenance_v1 table (Enforces Synthetic Technical source_row_id)
    op.create_table(
        'ods_member_provenance_v1',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('cinq_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_identifier_hash', sa.String(64), nullable=False),
        sa.Column('source_row_id', sa.String(64), nullable=False),
        sa.Column('survivorship_winner', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.CheckConstraint(
            "source_row_id ~ '^row_[0-9]+_[0-9a-f]{16}$|^[0-9a-fA-F-]{36}$'",
            name='chk_synthetic_source_row_id'
        ),
        schema='internal_ods'
    )

    # 10. Triggers for ODS Model Version and Claim/Claim-Line Integrity (Blockers 4 & 5)
    op.execute("""
    CREATE OR REPLACE FUNCTION fn_check_ods_batch_version_match()
    RETURNS TRIGGER AS $$
    DECLARE
        v_batch_version UUID;
    BEGIN
        SELECT ods_model_version_id INTO v_batch_version FROM batches WHERE id = NEW.batch_id;
        IF v_batch_version IS NULL THEN
            RAISE EXCEPTION 'Model Version Integrity Violation: Batch % has no ODS model version assigned', NEW.batch_id
            USING ERRCODE = 'check_violation';
        END IF;
        IF v_batch_version != NEW.ods_model_version_id THEN
            RAISE EXCEPTION 'Model Version Integrity Violation: Row ODS model version % does not match Batch % model version %',
                NEW.ods_model_version_id, NEW.batch_id, v_batch_version
            USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_check_ods_members_batch_version ON internal_ods.ods_members_v1;
    CREATE TRIGGER trg_check_ods_members_batch_version
    BEFORE INSERT OR UPDATE ON internal_ods.ods_members_v1
    FOR EACH ROW EXECUTE FUNCTION fn_check_ods_batch_version_match();

    DROP TRIGGER IF EXISTS trg_check_ods_claims_batch_version ON internal_ods.ods_claims_v1;
    CREATE TRIGGER trg_check_ods_claims_batch_version
    BEFORE INSERT OR UPDATE ON internal_ods.ods_claims_v1
    FOR EACH ROW EXECUTE FUNCTION fn_check_ods_batch_version_match();

    DROP TRIGGER IF EXISTS trg_check_ods_claim_lines_batch_version ON internal_ods.ods_claim_lines_v1;
    CREATE TRIGGER trg_check_ods_claim_lines_batch_version
    BEFORE INSERT OR UPDATE ON internal_ods.ods_claim_lines_v1
    FOR EACH ROW EXECUTE FUNCTION fn_check_ods_batch_version_match();

    CREATE OR REPLACE FUNCTION fn_check_claim_line_parent_match()
    RETURNS TRIGGER AS $$
    DECLARE
        v_claim RECORD;
    BEGIN
        SELECT batch_id, ods_model_version_id INTO v_claim FROM internal_ods.ods_claims_v1 WHERE claim_id = NEW.claim_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Claim Integrity Violation: Claim line references non-existent claim %', NEW.claim_id
            USING ERRCODE = 'foreign_key_violation';
        END IF;
        IF v_claim.batch_id != NEW.batch_id THEN
            RAISE EXCEPTION 'Claim Integrity Violation: Claim line batch % does not match Claim batch %', NEW.batch_id, v_claim.batch_id
            USING ERRCODE = 'check_violation';
        END IF;
        IF v_claim.ods_model_version_id != NEW.ods_model_version_id THEN
            RAISE EXCEPTION 'Claim Integrity Violation: Claim line model version % does not match Claim model version %', NEW.ods_model_version_id, v_claim.ods_model_version_id
            USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_check_ods_claim_line_parent_match ON internal_ods.ods_claim_lines_v1;
    CREATE TRIGGER trg_check_ods_claim_line_parent_match
    BEFORE INSERT OR UPDATE ON internal_ods.ods_claim_lines_v1
    FOR EACH ROW EXECUTE FUNCTION fn_check_claim_line_parent_match();
    """)

    # 11. Schema Security: Revoke public access to internal_ods
    op.execute("REVOKE ALL ON SCHEMA internal_ods FROM PUBLIC;")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA internal_ods FROM PUBLIC;")


def downgrade() -> None:
    op.drop_table('ods_member_provenance_v1', schema='internal_ods')
    op.drop_table('ods_claim_lines_v1', schema='internal_ods')
    op.drop_table('ods_claims_v1', schema='internal_ods')
    op.drop_table('ods_members_v1', schema='internal_ods')
    op.drop_column('batches', 'ods_model_version_id')
    op.drop_table('consumer_registrations')
    op.execute("DROP TRIGGER IF EXISTS trg_protect_published_ods_model_versions ON ods_model_versions;")
    op.execute("DROP FUNCTION IF EXISTS fn_protect_published_ods_model_versions();")
    op.drop_table('ods_model_versions')
    op.execute("DROP SCHEMA IF EXISTS ods_certified CASCADE;")
    op.execute("DROP SCHEMA IF EXISTS internal_ods CASCADE;")
