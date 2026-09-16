"""Wave 0 initial schema — all 15 tables

Revision ID: 001_wave0_initial
Revises: 
Create Date: 2026-09-04
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_wave0_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === ENUMS ===
    op.execute("CREATE TYPE auth_provider_enum AS ENUM ('mock', 'entra')")
    op.execute("CREATE TYPE role_enum AS ENUM ('ENGINEER','READ_ONLY','BUSINESS_ANALYST','DATA_STEWARD','OPERATIONS','APPROVER','ADMINISTRATOR')")
    op.execute("CREATE TYPE contract_status_enum AS ENUM ('DRAFT','CONFIRMED','RETIRED')")
    op.execute("CREATE TYPE unknown_status_enum AS ENUM ('OPEN','CONFIRMED','WONT_FIX')")
    op.execute("CREATE TYPE risk_level_enum AS ENUM ('LOW','MEDIUM','HIGH','CRITICAL')")
    op.execute("CREATE TYPE feed_format_enum AS ENUM ('CSV','JSON','PARQUET','XML','HL7','X12')")
    op.execute("CREATE TYPE feed_status_enum AS ENUM ('DRAFT','ACTIVE','INACTIVE','RETIRED')")
    op.execute("CREATE TYPE feed_version_status_enum AS ENUM ('DRAFT','PUBLISHED','SUPERSEDED','RETIRED')")
    op.execute("CREATE TYPE batch_status_enum AS ENUM ('PENDING','RUNNING','SUCCESS','FAILED','CANCELLED','FAILED_RECONCILIATION')")
    op.execute("CREATE TYPE stage_name_enum AS ENUM ('LANDING','BRONZE','SILVER_RAW')")
    op.execute("CREATE TYPE stage_status_enum AS ENUM ('PENDING','RUNNING','SUCCESS','FAILED','SKIPPED')")
    op.execute("CREATE TYPE input_status_enum AS ENUM ('ACCEPTED','DUPLICATE','REJECTED')")
    op.execute("CREATE TYPE quarantine_reason_enum AS ENUM ('INVALID_FIELD_TYPE','MISSING_REQUIRED_FIELD','FUTURE_DATE','INVALID_DATE_FORMAT','INVALID_ENUM_VALUE','VALUE_OUT_OF_RANGE','DUPLICATE_RECORD','REFERENTIAL_INTEGRITY','REGEX_MISMATCH','RECORD_TOO_LONG','ENCODING_ERROR')")
    op.execute("CREATE TYPE reconciliation_status_enum AS ENUM ('PASS','FAIL','PENDING')")
    op.execute("""CREATE TYPE audit_action_enum AS ENUM (
        'auth.login','auth.logout','auth.failed',
        'contract.created','contract.updated','contract.unknown_added','contract.unknown_confirmed',
        'feed.created','feed.updated','feed.status_changed','feed_version.created','feed_version.published',
        'input.registered','input.duplicate_detected','input.rejected',
        'batch.created','batch.started','batch.completed','batch.failed','batch.cancelled','batch.restart_requested',
        'stage.started','stage.completed','stage.failed',
        'quarantine.record_added',
        'reconciliation.computed','reconciliation.failed'
    )""")

    # === USERS ===
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("auth_provider", postgresql.ENUM(name="auth_provider_enum", create_type=False), nullable=False),
        sa.Column("auth_provider_id", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_auth_provider_id", "users", ["auth_provider_id"])
    op.create_index("ix_users_auth_provider_id_provider", "users", ["auth_provider_id", "auth_provider"], unique=True)

    # === ROLES ===
    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", postgresql.ENUM(name="role_enum", create_type=False), nullable=False, unique=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )

    # === USER_ROLES ===
    op.create_table(
        "user_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", postgresql.ENUM(name="role_enum", create_type=False), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("roles.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_user_roles_user_role", "user_roles", ["user_id", "role"], unique=True)

    # === SESSIONS ===
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jwt_jti", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_jwt_jti", "sessions", ["jwt_jti"], unique=True)

    # === CONTRACT REGISTER ===
    op.create_table(
        "contract_register_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_system", sa.String(255), nullable=False),
        sa.Column("target_domain", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("data_owner", sa.String(255), nullable=False),
        sa.Column("status", postgresql.ENUM(name="contract_status_enum", create_type=False), nullable=False, server_default="DRAFT"),
        sa.Column("story_id", sa.String(50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_contract_story_id", "contract_register_entries", ["story_id"])
    op.create_index("ix_contract_source_domain", "contract_register_entries", ["source_system", "target_domain"])

    op.create_table(
        "contract_unknowns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("contract_entry_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("contract_register_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("risk_level", postgresql.ENUM(name="risk_level_enum", create_type=False), nullable=False, server_default="MEDIUM"),
        sa.Column("status", postgresql.ENUM(name="unknown_status_enum", create_type=False), nullable=False, server_default="OPEN"),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("confirmed_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_contract_unknowns_entry", "contract_unknowns", ["contract_entry_id"])

    # === FEEDS ===
    op.create_table(
        "feeds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("format", postgresql.ENUM(name="feed_format_enum", create_type=False), nullable=False),
        sa.Column("landing_folder", sa.String(500), nullable=False),
        sa.Column("filename_pattern", sa.String(255), nullable=False),
        sa.Column("schedule_expression", sa.String(100), nullable=False, server_default="manual"),
        sa.Column("status", postgresql.ENUM(name="feed_status_enum", create_type=False), nullable=False, server_default="DRAFT"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_feeds_name", "feeds", ["name"], unique=True)
    op.create_index("ix_feeds_domain", "feeds", ["domain"])

    op.create_table(
        "feed_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("feed_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", postgresql.ENUM(name="feed_version_status_enum", create_type=False), nullable=False, server_default="DRAFT"),
        sa.Column("config_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("change_notes", sa.Text(), nullable=True),
        sa.Column("published_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_feed_versions_feed_version", "feed_versions", ["feed_id", "version_number"], unique=True)

    # === INPUT REGISTRY ===
    op.create_table(
        "input_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("feed_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("feeds.id"), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("file_fingerprint", sa.String(64), nullable=False),  # SHA-256 hex
        sa.Column("status", postgresql.ENUM(name="input_status_enum", create_type=False), nullable=False, server_default="ACCEPTED"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("registered_by", sa.String(255), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_input_registry_fingerprint", "input_registry", ["file_fingerprint"], unique=True)
    op.create_index("ix_input_registry_feed", "input_registry", ["feed_id"])
    op.create_index("ix_input_registry_feed_filename", "input_registry", ["feed_id", "filename"])

    # === BATCHES ===
    op.create_table(
        "batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("feed_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("feeds.id"), nullable=False),
        sa.Column("feed_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("feed_versions.id"), nullable=False),
        sa.Column("input_registry_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("input_registry.id"), nullable=True),
        sa.Column("status", postgresql.ENUM(name="batch_status_enum", create_type=False), nullable=False, server_default="PENDING"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triggered_by", sa.String(255), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("restart_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_batches_feed_id", "batches", ["feed_id"])
    op.create_index("ix_batches_status", "batches", ["status"])
    op.create_index("ix_batches_input_registry_id", "batches", ["input_registry_id"])

    # === BATCH STAGES ===
    op.create_table(
        "batch_stages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage_name", postgresql.ENUM(name="stage_name_enum", create_type=False), nullable=False),
        sa.Column("stage_order", sa.Integer(), nullable=False),
        sa.Column("status", postgresql.ENUM(name="stage_status_enum", create_type=False), nullable=False, server_default="PENDING"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rows_in", sa.Integer(), nullable=True),
        sa.Column("rows_out", sa.Integer(), nullable=True),
        sa.Column("rows_quarantined", sa.Integer(), nullable=True),
        sa.Column("rows_dropped", sa.Integer(), nullable=True),
        sa.Column("output_path", sa.String(1000), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("stage_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_batch_stages_batch_id", "batch_stages", ["batch_id"])
    op.create_index("ix_batch_stages_batch_stage", "batch_stages", ["batch_id", "stage_name"], unique=True)

    # === QUARANTINE RECORDS ===
    op.create_table(
        "quarantine_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage_name", sa.String(50), nullable=False),
        sa.Column("source_row_number", sa.BigInteger(), nullable=True),
        sa.Column("source_record_raw", sa.Text(), nullable=True),
        sa.Column("field_name", sa.String(255), nullable=True),
        sa.Column("field_value", sa.Text(), nullable=True),
        sa.Column("reason", postgresql.ENUM(name="quarantine_reason_enum", create_type=False), nullable=False),
        sa.Column("reason_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_quarantine_batch_id", "quarantine_records", ["batch_id"])
    op.create_index("ix_quarantine_batch_stage", "quarantine_records", ["batch_id", "stage_name"])

    # === BATCH RECONCILIATION ===
    op.create_table(
        "batch_reconciliation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("rows_in", sa.Integer(), nullable=False),
        sa.Column("rows_silver_raw", sa.Integer(), nullable=False),
        sa.Column("rows_quarantined", sa.Integer(), nullable=False),
        sa.Column("rows_dropped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("balance_check_passed", sa.Boolean(), nullable=False),
        sa.Column("status", postgresql.ENUM(name="reconciliation_status_enum", create_type=False), nullable=False, server_default="PENDING"),
        sa.Column("discrepancy", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_batch_reconciliation_batch", "batch_reconciliation", ["batch_id"], unique=True)

    op.create_table(
        "reconciliation_ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("reconciliation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("batch_reconciliation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason_code", sa.String(100), nullable=False),
        sa.Column("reason_description", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_ledger_recon_reason", "reconciliation_ledger_entries", ["reconciliation_id", "reason_code"])

    # === AUDIT EVENTS ===
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("action", postgresql.ENUM(name="audit_action_enum", create_type=False), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("actor_email", sa.String(255), nullable=True),
        sa.Column("object_type", sa.String(100), nullable=False),
        sa.Column("object_id", sa.String(255), nullable=True),
        sa.Column("before_state", postgresql.JSONB(), nullable=True),
        sa.Column("after_state", postgresql.JSONB(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_audit_actor_action", "audit_events", ["actor_id", "action"])
    op.create_index("ix_audit_object", "audit_events", ["object_type", "object_id"])
    op.create_index("ix_audit_action", "audit_events", ["action"])
    op.create_index("ix_audit_correlation", "audit_events", ["correlation_id"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("reconciliation_ledger_entries")
    op.drop_table("batch_reconciliation")
    op.drop_table("quarantine_records")
    op.drop_table("batch_stages")
    op.drop_table("batches")
    op.drop_table("input_registry")
    op.drop_table("feed_versions")
    op.drop_table("feeds")
    op.drop_table("contract_unknowns")
    op.drop_table("contract_register_entries")
    op.drop_table("sessions")
    op.drop_table("user_roles")
    op.drop_table("roles")
    op.drop_table("users")

    # Drop enums
    for enum_name in [
        "audit_action_enum", "reconciliation_status_enum", "quarantine_reason_enum",
        "input_status_enum", "stage_status_enum", "stage_name_enum", "batch_status_enum",
        "feed_version_status_enum", "feed_status_enum", "feed_format_enum",
        "risk_level_enum", "unknown_status_enum", "contract_status_enum",
        "role_enum", "auth_provider_enum",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
