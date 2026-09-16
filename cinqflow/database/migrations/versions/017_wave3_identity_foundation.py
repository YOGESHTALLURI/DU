"""Wave 3 Slice 3: Identity Foundation and Identity Exceptions

Revision ID: 017_wave3_identity_foundation
Revises: 016_wave3_canonical_ods_models
Create Date: 2026-09-09 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "017_wave3_identity_foundation"
down_revision: Union[str, None] = "016_wave3_canonical_ods_models"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Enable btree_gist extension for exclusion constraints on scalar types
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")

    # 2. master_identities
    op.create_table(
        "master_identities",
        sa.Column("cinq_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("identity_type", sa.String(length=50), nullable=False, server_default="INDIVIDUAL"),
        sa.Column("merged_into_cinq_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("master_identities.cinq_id", ondelete="SET NULL"), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'MERGED')", name="chk_master_identity_status"),
        sa.UniqueConstraint("id", name="uq_master_identities_id"),
    )
    op.create_index("ix_master_identities_status", "master_identities", ["status"])
    op.create_index("ix_master_identities_merged_into", "master_identities", ["merged_into_cinq_id"])

    # Trigger: Prevent physical deletion of master_identities
    op.execute("""
    CREATE OR REPLACE FUNCTION trg_prevent_identity_delete()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION 'Physical DELETE on master_identities is strictly prohibited. Use soft status update.';
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_prevent_master_identities_delete ON master_identities;
    CREATE TRIGGER trg_prevent_master_identities_delete
    BEFORE DELETE ON master_identities
    FOR EACH ROW EXECUTE FUNCTION trg_prevent_identity_delete();
    """)

    # 3. identity_tokens
    op.create_table(
        "identity_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("cinq_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("master_identities.cinq_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ssn_hash", sa.String(length=64), nullable=True),
        sa.Column("dob_hash", sa.String(length=64), nullable=True),
        sa.Column("last_name_hash", sa.String(length=64), nullable=True),
        sa.Column("first_name_hash", sa.String(length=64), nullable=True),
        sa.Column("gender_hash", sa.String(length=64), nullable=True),
        sa.Column("postal_code_hash", sa.String(length=64), nullable=True),
        sa.Column("pepper_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="TRUE"),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_period", postgresql.TSTZRANGE(), sa.Computed("tstzrange(effective_from, effective_to, '[)')", persisted=True), nullable=True),
        sa.Column("source_feed_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("feeds.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "(is_current = TRUE AND effective_to IS NULL) OR (is_current = FALSE AND effective_to IS NOT NULL AND effective_to > effective_from)",
            name="chk_identity_tokens_temporal"
        ),
    )
    op.create_index("ix_identity_tokens_cinq_id", "identity_tokens", ["cinq_id"])
    op.create_index("ix_identity_tokens_ssn_current", "identity_tokens", ["ssn_hash"], postgresql_where=sa.text("is_current = TRUE AND ssn_hash IS NOT NULL"))
    op.create_index("ix_identity_tokens_name_dob_current", "identity_tokens", ["last_name_hash", "dob_hash"], postgresql_where=sa.text("is_current = TRUE AND last_name_hash IS NOT NULL AND dob_hash IS NOT NULL"))
    op.create_index("uq_identity_tokens_cinq_id_current", "identity_tokens", ["cinq_id"], unique=True, postgresql_where=sa.text("is_current = TRUE"))

    # Exclusion constraint on identity_tokens temporal overlap
    op.execute("""
    ALTER TABLE identity_tokens
    ADD CONSTRAINT excl_identity_tokens_temporal_overlap
    EXCLUDE USING gist (
        cinq_id WITH =,
        effective_period WITH &&
    );
    """)

    # 4. identity_crosswalk
    op.create_table(
        "identity_crosswalk",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("cinq_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("master_identities.cinq_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_system", sa.String(length=100), nullable=False),
        sa.Column("source_identifier_hash", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="TRUE"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_period", postgresql.TSTZRANGE(), sa.Computed("tstzrange(valid_from, valid_to, '[)')", persisted=True), nullable=True),
        sa.Column("match_score", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("match_type", sa.String(length=50), nullable=False),
        sa.Column("source_feed_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("feeds.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "(is_active = TRUE AND valid_to IS NULL) OR (is_active = FALSE AND valid_to IS NOT NULL AND valid_to > valid_from)",
            name="chk_crosswalk_active_temporal_consistency"
        ),
    )
    op.create_index("ix_crosswalk_cinq_id", "identity_crosswalk", ["cinq_id"])
    op.create_index("ix_crosswalk_source_composite", "identity_crosswalk", ["source_system", "source_identifier_hash"])
    op.create_index("uq_active_crosswalk_source", "identity_crosswalk", ["source_system", "source_identifier_hash"], unique=True, postgresql_where=sa.text("is_active = TRUE"))

    # Exclusion constraint on temporal overlap
    op.execute("""
    ALTER TABLE identity_crosswalk
    ADD CONSTRAINT excl_crosswalk_temporal_overlap
    EXCLUDE USING gist (
        source_system WITH =,
        source_identifier_hash WITH =,
        valid_period WITH &&
    );
    """)

    # 5. identity_exceptions
    op.create_table(
        "identity_exceptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feed_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_system", sa.String(length=100), nullable=False),
        sa.Column("source_identifier_hash", sa.String(length=64), nullable=False),
        sa.Column("record_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_matches_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("highest_score", sa.Numeric(precision=5, scale=2), nullable=False, server_default="0.00"),
        sa.Column("exception_type", sa.String(length=50), nullable=False, server_default="AMBIGUOUS_MATCH"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("assigned_steward", sa.String(length=255), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_type", sa.String(length=50), nullable=True),
        sa.Column("resolved_cinq_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("master_identities.cinq_id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "(status = 'RESOLVED' AND resolution_type IS NOT NULL AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL) OR (status != 'RESOLVED')",
            name="chk_exception_resolution_consistency"
        ),
    )
    op.create_index("ix_exceptions_batch_status", "identity_exceptions", ["batch_id", "status"])
    op.create_index("ix_exceptions_feed_status", "identity_exceptions", ["feed_id", "status"])
    op.create_index("ix_exceptions_status", "identity_exceptions", ["status"])
    op.create_index("ix_exceptions_assigned_steward", "identity_exceptions", ["assigned_steward"])

    # 6. identity_decisions
    op.create_table(
        "identity_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("exception_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("identity_exceptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision_type", sa.String(length=50), nullable=False),
        sa.Column("cinq_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("master_identities.cinq_id", ondelete="RESTRICT"), nullable=True),
        sa.Column("decided_by", sa.String(length=255), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("decision_notes", sa.Text(), nullable=False),
        sa.Column("pre_resolution_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("post_resolution_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "decision_type IN ('LINK_EXISTING', 'CREATE_NEW', 'DEFER')",
            name="chk_decision_type_valid"
        ),
        sa.CheckConstraint(
            "(decision_type IN ('LINK_EXISTING', 'CREATE_NEW') AND cinq_id IS NOT NULL) OR (decision_type = 'DEFER' AND cinq_id IS NULL)",
            name="chk_decision_cinq_id_semantics"
        ),
    )
    op.create_index("ix_decisions_exception_id", "identity_decisions", ["exception_id"])
    op.create_index("ix_decisions_cinq_id", "identity_decisions", ["cinq_id"])
    op.create_index("ix_decisions_decided_at", "identity_decisions", ["decided_at"])

    # Trigger: Prevent mutation/deletion of identity_decisions
    op.execute("""
    CREATE OR REPLACE FUNCTION trg_prevent_decision_mutation()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION 'identity_decisions is append-only and immutable. UPDATE and DELETE are prohibited.';
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_prevent_identity_decisions_mutation ON identity_decisions;
    CREATE TRIGGER trg_prevent_identity_decisions_mutation
    BEFORE UPDATE OR DELETE ON identity_decisions
    FOR EACH ROW EXECUTE FUNCTION trg_prevent_decision_mutation();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_prevent_identity_decisions_mutation ON identity_decisions;")
    op.execute("DROP FUNCTION IF EXISTS trg_prevent_decision_mutation();")
    op.execute("DROP TRIGGER IF EXISTS trg_prevent_master_identities_delete ON master_identities;")
    op.execute("DROP FUNCTION IF EXISTS trg_prevent_identity_delete();")

    op.drop_table("identity_decisions")
    op.drop_table("identity_exceptions")
    op.drop_table("identity_crosswalk")
    op.drop_table("identity_tokens")
    op.drop_table("master_identities")
