"""Wave 1 Slice 1: Profiling and Schema Contracts schema

Revision ID: 002_wave1_profiling_and_schemas
Revises: 001_wave0_initial
Create Date: 2026-09-04
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002_wave1_profiling_and_schemas"
down_revision: Union[str, None] = "001_wave0_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === ENUMS ===
    op.execute("CREATE TYPE schema_data_type_enum AS ENUM ('STRING', 'INTEGER', 'DECIMAL', 'BOOLEAN', 'DATE', 'TIMESTAMP')")
    op.execute("CREATE TYPE schema_version_status_enum AS ENUM ('DRAFT', 'PUBLISHED', 'SUPERSEDED', 'RETIRED')")
    op.execute("CREATE TYPE profiling_run_status_enum AS ENUM ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')")

    # Add new values to audit_action_enum
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'sample.uploaded'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'profiling.started'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'profiling.completed'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'profiling.failed'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'schema.created'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'schema.draft_updated'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'schema.version_created'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'schema.published'")

    # === SAMPLE FILES ===
    op.create_table(
        "sample_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("feed_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("storage_path", sa.String(1000), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("file_fingerprint", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False, server_default="text/csv"),
        sa.Column("row_count_estimate", sa.Integer(), nullable=True),
        sa.Column("uploaded_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_sample_files_feed_id", "sample_files", ["feed_id"])
    op.create_index("ix_sample_files_file_fingerprint", "sample_files", ["file_fingerprint"])

    # === PROFILING RUNS ===
    op.create_table(
        "profiling_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("feed_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sample_file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sample_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", postgresql.ENUM(name="profiling_run_status_enum", create_type=False), nullable=False, server_default="PENDING"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("column_count", sa.Integer(), nullable=True),
        sa.Column("profiling_summary", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_profiling_runs_feed_id", "profiling_runs", ["feed_id"])
    op.create_index("ix_profiling_runs_sample_file_id", "profiling_runs", ["sample_file_id"])
    op.create_index("ix_profiling_runs_status", "profiling_runs", ["status"])

    # === PROFILING COLUMN STATS ===
    op.create_table(
        "profiling_column_stats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("profiling_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("profiling_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("column_name", sa.String(255), nullable=False),
        sa.Column("ordinal_position", sa.Integer(), nullable=False),
        sa.Column("inferred_type", postgresql.ENUM(name="schema_data_type_enum", create_type=False), nullable=False),
        sa.Column("null_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("null_percentage", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("distinct_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_percentage", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("min_value", sa.String(500), nullable=True),
        sa.Column("max_value", sa.String(500), nullable=True),
        sa.Column("sample_values", postgresql.JSONB(), nullable=True),
        sa.Column("detected_date_patterns", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_profiling_column_stats_profiling_run_id", "profiling_column_stats", ["profiling_run_id"])
    op.create_index("ix_profiling_col_run_ord", "profiling_column_stats", ["profiling_run_id", "ordinal_position"])

    # === SCHEMAS ===
    op.create_table(
        "schemas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("feed_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_schemas_feed_id", "schemas", ["feed_id"])
    op.create_index("ix_schemas_name", "schemas", ["name"])

    # === SCHEMA VERSIONS ===
    op.create_table(
        "schema_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("schema_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("schemas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", postgresql.ENUM(name="schema_version_status_enum", create_type=False), nullable=False, server_default="DRAFT"),
        sa.Column("change_notes", sa.Text(), nullable=True),
        sa.Column("source_profiling_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("profiling_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_sample_file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sample_files.id", ondelete="SET NULL"), nullable=True),
        sa.Column("published_by", sa.String(255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_schema_versions_schema_id", "schema_versions", ["schema_id"])
    op.create_index("ix_schema_versions_status", "schema_versions", ["status"])
    op.create_index("ix_schema_versions_source_profiling_run_id", "schema_versions", ["source_profiling_run_id"])
    op.create_index("ix_schema_versions_source_sample_file_id", "schema_versions", ["source_sample_file_id"])
    op.create_index("ix_schema_version_schema_id_ver", "schema_versions", ["schema_id", "version_number"], unique=True)

    # === SCHEMA FIELDS ===
    op.create_table(
        "schema_fields",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("schema_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("schema_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_name", sa.String(255), nullable=False),
        sa.Column("ordinal_position", sa.Integer(), nullable=False),
        sa.Column("data_type", postgresql.ENUM(name="schema_data_type_enum", create_type=False), nullable=False),
        sa.Column("is_nullable", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("format_pattern", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_schema_fields_schema_version_id", "schema_fields", ["schema_version_id"])
    op.create_index("ix_schema_field_ver_ord", "schema_fields", ["schema_version_id", "ordinal_position"])
    op.create_index("ix_schema_field_ver_name", "schema_fields", ["schema_version_id", "field_name"], unique=True)


def downgrade() -> None:
    op.drop_table("schema_fields")
    op.drop_table("schema_versions")
    op.drop_table("schemas")
    op.drop_table("profiling_column_stats")
    op.drop_table("profiling_runs")
    op.drop_table("sample_files")
    op.execute("DROP TYPE profiling_run_status_enum")
    op.execute("DROP TYPE schema_version_status_enum")
    op.execute("DROP TYPE schema_data_type_enum")
