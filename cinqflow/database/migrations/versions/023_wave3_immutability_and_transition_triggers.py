'''Alembic migration 023: immutability trigger on identity_merge_split_event,
status transition enforcement trigger on master_identities,
and source coordinates columns on identity_merge_split_proposal.
'''

from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as psql

# revision identifiers, used by Alembic.
revision = '023_wave3_immutability_and_transition_triggers'
down_revision = '022_create_identity_run_status'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add source_system and source_identifier_hash to identity_merge_split_proposal
    op.add_column(
        'identity_merge_split_proposal',
        sa.Column('source_system', sa.String(length=100), nullable=True)
    )
    op.add_column(
        'identity_merge_split_proposal',
        sa.Column('source_identifier_hash', sa.String(length=64), nullable=True)
    )

    # 2. Database-level trigger prohibiting UPDATE and DELETE on identity_merge_split_event
    op.execute("""
    CREATE OR REPLACE FUNCTION fn_prevent_merge_split_event_mutation()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION 'identity_merge_split_event is append-only and immutable. UPDATE and DELETE are prohibited.'
        USING ERRCODE = 'check_violation';
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_prevent_identity_merge_split_event_mutation ON identity_merge_split_event;
    CREATE TRIGGER trg_prevent_identity_merge_split_event_mutation
    BEFORE UPDATE OR DELETE ON identity_merge_split_event
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_merge_split_event_mutation();
    """)

    # 3. Database-level trigger preventing illegal status transitions on master_identities
    op.execute("""
    CREATE OR REPLACE FUNCTION fn_enforce_master_identity_status_transition()
    RETURNS TRIGGER AS $$
    BEGIN
        IF OLD.status = NEW.status THEN
            RETURN NEW;
        END IF;

        -- Legal transitions:
        -- ACTIVE -> INACTIVE, MERGED
        -- INACTIVE -> ACTIVE
        -- MERGED -> None (immutable)
        IF OLD.status = 'ACTIVE' AND NEW.status IN ('INACTIVE', 'MERGED') THEN
            RETURN NEW;
        ELSIF OLD.status = 'INACTIVE' AND NEW.status = 'ACTIVE' THEN
            RETURN NEW;
        ELSE
            RAISE EXCEPTION 'Illegal status transition on master_identities: % to % is prohibited', OLD.status, NEW.status USING ERRCODE = 'check_violation';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_enforce_master_identity_status_transition ON master_identities;
    CREATE TRIGGER trg_enforce_master_identity_status_transition
    BEFORE UPDATE OF status ON master_identities
    FOR EACH ROW EXECUTE FUNCTION fn_enforce_master_identity_status_transition();
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_enforce_master_identity_status_transition ON master_identities;")
    op.execute("DROP FUNCTION IF EXISTS fn_enforce_master_identity_status_transition();")

    op.execute("DROP TRIGGER IF EXISTS trg_prevent_identity_merge_split_event_mutation ON identity_merge_split_event;")
    op.execute("DROP FUNCTION IF EXISTS fn_prevent_merge_split_event_mutation();")

    op.drop_column('identity_merge_split_proposal', 'source_identifier_hash')
    op.drop_column('identity_merge_split_proposal', 'source_system')
