"""Alembic migration 024: ODS Certification and Consumer Compatibility Gate (CF-V3-E10-03).
Creates ods_certifications table with transition protection trigger,
provisions certified views in ods_certified schema,
and establishes the downstream consumer role privilege boundary.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '024_ods_certification_and_consumer_gate'
down_revision = '023_wave3_immutability_and_transition_triggers'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add audit actions for ODS certification
    for act in [
        'ods.batch_certified',
        'ods.batch_certification_failed',
        'ods.batch_certification_revoked',
    ]:
        op.execute(f"ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS '{act}'")

    # 2. Create ods_certifications table
    op.create_table(
        'ods_certifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('batches.id', ondelete='RESTRICT'), nullable=False, unique=True),
        sa.Column('ods_model_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('ods_model_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='PENDING'),
        sa.Column('certified_by', sa.String(255), nullable=True),
        sa.Column('certified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('certification_notes', sa.Text(), nullable=True),
        sa.Column('checklist_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('updated_by', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.CheckConstraint("status IN ('PENDING', 'CERTIFIED', 'FAILED')", name='chk_ods_certification_status'),
    )

    op.create_index('ix_ods_certifications_batch_id', 'ods_certifications', ['batch_id'])
    op.create_index('ix_ods_certifications_status', 'ods_certifications', ['status'])

    # 3. Transition and immutability protection trigger for ods_certifications
    op.execute("""
    CREATE OR REPLACE FUNCTION fn_protect_ods_certification_transition()
    RETURNS TRIGGER AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'ods_certifications records are append-only and immutable. DELETE operations are strictly prohibited.'
            USING ERRCODE = 'check_violation';
        END IF;

        IF TG_OP = 'UPDATE' THEN
            -- Once sealed in CERTIFIED or FAILED, no updates to any fields are permitted
            IF OLD.status IN ('CERTIFIED', 'FAILED') THEN
                RAISE EXCEPTION 'ods_certifications record % is sealed in % status and cannot be modified.', OLD.id, OLD.status
                USING ERRCODE = 'check_violation';
            END IF;

            -- If status is PENDING, only transition to CERTIFIED or FAILED is permitted
            IF NEW.status NOT IN ('PENDING', 'CERTIFIED', 'FAILED') THEN
                RAISE EXCEPTION 'Invalid status transition on ods_certifications from % to %', OLD.status, NEW.status
                USING ERRCODE = 'check_violation';
            END IF;

            -- Immutable core coordinates even during PENDING status
            IF NEW.batch_id != OLD.batch_id THEN
                RAISE EXCEPTION 'batch_id on ods_certifications is immutable'
                USING ERRCODE = 'check_violation';
            END IF;

            IF NEW.ods_model_version_id != OLD.ods_model_version_id THEN
                RAISE EXCEPTION 'ods_model_version_id on ods_certifications is immutable'
                USING ERRCODE = 'check_violation';
            END IF;

            IF NEW.created_at != OLD.created_at THEN
                RAISE EXCEPTION 'created_at on ods_certifications is immutable'
                USING ERRCODE = 'check_violation';
            END IF;

            IF NEW.created_by != OLD.created_by THEN
                RAISE EXCEPTION 'created_by on ods_certifications is immutable'
                USING ERRCODE = 'check_violation';
            END IF;

            RETURN NEW;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_protect_ods_certification_transition ON ods_certifications;
    CREATE TRIGGER trg_protect_ods_certification_transition
    BEFORE UPDATE OR DELETE ON ods_certifications
    FOR EACH ROW EXECUTE FUNCTION fn_protect_ods_certification_transition();
    """)

    # 4. Create certified views in ods_certified schema
    op.execute("""
    CREATE OR REPLACE VIEW ods_certified.members_v1 AS
    SELECT m.cinq_id, m.batch_id, m.ods_model_version_id, m.first_name, m.last_name,
           m.date_of_birth, m.gender, m.address_line1, m.city, m.state, m.postal_code,
           m.survivorship_applied, m.created_at, m.updated_at
    FROM internal_ods.ods_members_v1 m
    JOIN ods_certifications c ON m.batch_id = c.batch_id
    WHERE c.status = 'CERTIFIED';

    CREATE OR REPLACE VIEW ods_certified.claims_v1 AS
    SELECT cl.claim_id, cl.cinq_id, cl.batch_id, cl.ods_model_version_id, cl.claim_type,
           cl.total_charge_amount, cl.claim_date, cl.created_at, cl.updated_at
    FROM internal_ods.ods_claims_v1 cl
    JOIN ods_certifications c ON cl.batch_id = c.batch_id
    WHERE c.status = 'CERTIFIED';

    CREATE OR REPLACE VIEW ods_certified.claim_lines_v1 AS
    SELECT cll.claim_line_id, cll.claim_id, cll.batch_id, cll.ods_model_version_id,
           cll.line_number, cll.service_date, cll.procedure_code, cll.allowed_amount,
           cll.paid_amount, cll.created_at, cll.updated_at
    FROM internal_ods.ods_claim_lines_v1 cll
    JOIN ods_certifications c ON cll.batch_id = c.batch_id
    WHERE c.status = 'CERTIFIED';
    """)

    # 5. Establish consumer base role and privilege boundary
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cinqflow_consumer_base') THEN
            CREATE ROLE cinqflow_consumer_base NOLOGIN;
        END IF;
    END $$;

    GRANT USAGE ON SCHEMA ods_certified TO cinqflow_consumer_base;
    GRANT SELECT ON ALL TABLES IN SCHEMA ods_certified TO cinqflow_consumer_base;
    ALTER DEFAULT PRIVILEGES IN SCHEMA ods_certified GRANT SELECT ON TABLES TO cinqflow_consumer_base;

    REVOKE ALL ON SCHEMA internal_ods FROM cinqflow_consumer_base;
    """)


def downgrade():
    op.execute("""
    DROP VIEW IF EXISTS ods_certified.claim_lines_v1;
    DROP VIEW IF EXISTS ods_certified.claims_v1;
    DROP VIEW IF EXISTS ods_certified.members_v1;
    DROP TRIGGER IF EXISTS trg_protect_ods_certification_transition ON ods_certifications;
    DROP FUNCTION IF EXISTS fn_protect_ods_certification_transition();
    """)
    op.drop_index('ix_ods_certifications_status', table_name='ods_certifications')
    op.drop_index('ix_ods_certifications_batch_id', table_name='ods_certifications')
    op.drop_table('ods_certifications')
