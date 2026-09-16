"""Wave 1 Slice 3: Canonical Models and Mappings

Revision ID: 004_canonical_and_mappings
Revises: 003_wave1_slice2_onboarding
Create Date: 2026-09-04
"""
from typing import Sequence, Union
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '004_canonical_and_mappings'
down_revision: Union[str, None] = '003_wave1_slice2_onboarding'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New audit actions
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'mapping.created'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'mapping.draft_updated'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'mapping.version_created'")
    op.execute("ALTER TYPE audit_action_enum ADD VALUE IF NOT EXISTS 'mapping.published'")

    # 2. New enums
    op.execute("DO $$ BEGIN CREATE TYPE mapping_version_status_enum AS ENUM ('DRAFT', 'PUBLISHED', 'SUPERSEDED', 'RETIRED'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE transform_type_enum AS ENUM ('DIRECT', 'CONSTANT', 'VALUE_MAP', 'DATE_FORMAT', 'CONCAT', 'STRING_CLEAN', 'COALESCE'); EXCEPTION WHEN duplicate_object THEN null; END $$;")

    # 3. Canonical Models table
    op.create_table(
        'canonical_models',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False, unique=True),
        sa.Column('domain', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.create_index('ix_canonical_models_name', 'canonical_models', ['name'])
    op.create_index('ix_canonical_models_domain', 'canonical_models', ['domain'])

    # 4. Canonical Fields table
    op.create_table(
        'canonical_fields',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('canonical_model_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('canonical_models.id', ondelete='CASCADE'), nullable=False),
        sa.Column('field_name', sa.String(255), nullable=False),
        sa.Column('data_type', postgresql.ENUM('STRING', 'INTEGER', 'DECIMAL', 'BOOLEAN', 'DATE', 'TIMESTAMP', name='schema_data_type_enum', create_type=False), nullable=False),
        sa.Column('is_required', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_nullable', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('ordinal_position', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.UniqueConstraint('canonical_model_id', 'field_name', name='uq_canonical_field_model_name'),
    )
    op.create_index('ix_canonical_fields_model_id', 'canonical_fields', ['canonical_model_id'])
    op.create_index('ix_canonical_fields_model_ord', 'canonical_fields', ['canonical_model_id', 'ordinal_position'])

    # 5. Mappings table
    op.create_table(
        'mappings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('feed_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feeds.id', ondelete='CASCADE'), nullable=False),
        sa.Column('schema_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('schemas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('canonical_model_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('canonical_models.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.UniqueConstraint('feed_id', 'canonical_model_id', name='uq_mapping_feed_canonical_model'),
    )
    op.create_index('ix_mappings_feed_id', 'mappings', ['feed_id'])
    op.create_index('ix_mappings_schema_id', 'mappings', ['schema_id'])
    op.create_index('ix_mappings_canonical_model_id', 'mappings', ['canonical_model_id'])

    # 6. Mapping Versions table
    op.create_table(
        'mapping_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('mapping_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mappings.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('schema_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('schema_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('status', postgresql.ENUM('DRAFT', 'PUBLISHED', 'SUPERSEDED', 'RETIRED', name='mapping_version_status_enum', create_type=False), nullable=False, server_default='DRAFT'),
        sa.Column('compiled_spec', postgresql.JSONB(), nullable=True),
        sa.Column('change_notes', sa.Text(), nullable=True),
        sa.Column('published_by', sa.String(255), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.UniqueConstraint('mapping_id', 'version_number', name='uq_mapping_version_ver'),
    )
    op.create_index('ix_mapping_versions_mapping_id', 'mapping_versions', ['mapping_id'])
    op.create_index('ix_mapping_versions_schema_ver_id', 'mapping_versions', ['schema_version_id'])
    op.create_index('ix_mapping_versions_status', 'mapping_versions', ['status'])

    # 7. Mapping Lines table
    op.create_table(
        'mapping_lines',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('mapping_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('mapping_versions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('canonical_field_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('canonical_fields.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('source_field_names', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('transform_type', postgresql.ENUM('DIRECT', 'CONSTANT', 'VALUE_MAP', 'DATE_FORMAT', 'CONCAT', 'STRING_CLEAN', 'COALESCE', name='transform_type_enum', create_type=False), nullable=False, server_default='DIRECT'),
        sa.Column('transform_params', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by', sa.String(255), nullable=False, server_default='system'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.UniqueConstraint('mapping_version_id', 'canonical_field_id', name='uq_mapping_line_ver_field'),
    )
    op.create_index('ix_mapping_lines_version_id', 'mapping_lines', ['mapping_version_id'])
    op.create_index('ix_mapping_lines_canonical_field_id', 'mapping_lines', ['canonical_field_id'])

    # 8. Seed Standard Reference Data for Canonical Models & Canonical Fields using raw SQL
    models_data = [
        {
            "id": "c0000000-0000-0000-0000-000000000001",
            "name": "Member",
            "domain": "Eligibility",
            "description": "Standard healthcare member/patient enrollment demographics and identity entity.",
            "fields": [
                {"name": "member_id", "type": "STRING", "required": True, "nullable": False, "desc": "Unique identifier for the health plan member", "ord": 1},
                {"name": "first_name", "type": "STRING", "required": True, "nullable": False, "desc": "Member legal given name", "ord": 2},
                {"name": "last_name", "type": "STRING", "required": True, "nullable": False, "desc": "Member legal surname", "ord": 3},
                {"name": "date_of_birth", "type": "DATE", "required": True, "nullable": False, "desc": "Member date of birth (ISO YYYY-MM-DD)", "ord": 4},
                {"name": "gender", "type": "STRING", "required": True, "nullable": False, "desc": "Member administrative gender (MALE, FEMALE, OTHER, UNKNOWN)", "ord": 5},
                {"name": "address_line1", "type": "STRING", "required": False, "nullable": True, "desc": "Primary residential street address", "ord": 6},
                {"name": "city", "type": "STRING", "required": False, "nullable": True, "desc": "Primary address city", "ord": 7},
                {"name": "state", "type": "STRING", "required": False, "nullable": True, "desc": "Two-letter US state postal code", "ord": 8},
                {"name": "postal_code", "type": "STRING", "required": False, "nullable": True, "desc": "Five or nine digit postal ZIP code", "ord": 9},
            ]
        },
        {
            "id": "c0000000-0000-0000-0000-000000000002",
            "name": "Claim",
            "domain": "Claims",
            "description": "Standard healthcare medical or pharmacy claim transaction entity.",
            "fields": [
                {"name": "claim_id", "type": "STRING", "required": True, "nullable": False, "desc": "Unique identifier for the claim transaction", "ord": 1},
                {"name": "member_id", "type": "STRING", "required": True, "nullable": False, "desc": "Identifier of the enrolled member receiving services", "ord": 2},
                {"name": "provider_id", "type": "STRING", "required": True, "nullable": False, "desc": "National Provider Identifier (NPI) or rendering provider code", "ord": 3},
                {"name": "service_date", "type": "DATE", "required": True, "nullable": False, "desc": "Date on which healthcare service was performed (ISO YYYY-MM-DD)", "ord": 4},
                {"name": "claim_amount", "type": "DECIMAL", "required": True, "nullable": False, "desc": "Total billed dollar amount for the claim", "ord": 5},
                {"name": "claim_status", "type": "STRING", "required": False, "nullable": True, "desc": "Adjudication status (PAID, DENIED, PENDING)", "ord": 6},
            ]
        },
        {
            "id": "c0000000-0000-0000-0000-000000000003",
            "name": "Encounter",
            "domain": "Clinical",
            "description": "Standard clinical healthcare encounter or inpatient/outpatient admission event.",
            "fields": [
                {"name": "encounter_id", "type": "STRING", "required": True, "nullable": False, "desc": "Unique identifier for the healthcare visit or encounter", "ord": 1},
                {"name": "patient_id", "type": "STRING", "required": True, "nullable": False, "desc": "Identifier of the patient", "ord": 2},
                {"name": "facility_id", "type": "STRING", "required": True, "nullable": False, "desc": "Identifier of the hospital or clinical facility", "ord": 3},
                {"name": "admit_date", "type": "DATE", "required": True, "nullable": False, "desc": "Encounter admission date (ISO YYYY-MM-DD)", "ord": 4},
                {"name": "discharge_date", "type": "DATE", "required": False, "nullable": True, "desc": "Encounter discharge date (ISO YYYY-MM-DD)", "ord": 5},
                {"name": "encounter_type", "type": "STRING", "required": False, "nullable": True, "desc": "Encounter classification (INPATIENT, OUTPATIENT, EMERGENCY)", "ord": 6},
            ]
        },
        {
            "id": "c0000000-0000-0000-0000-000000000004",
            "name": "Observation",
            "domain": "Clinical",
            "description": "Standard clinical observation, laboratory result, or vital sign measurement.",
            "fields": [
                {"name": "observation_id", "type": "STRING", "required": True, "nullable": False, "desc": "Unique identifier for the clinical observation measurement", "ord": 1},
                {"name": "patient_id", "type": "STRING", "required": True, "nullable": False, "desc": "Identifier of the patient", "ord": 2},
                {"name": "observation_code", "type": "STRING", "required": True, "nullable": False, "desc": "Standard LOINC or clinical measurement code", "ord": 3},
                {"name": "observation_date", "type": "DATE", "required": True, "nullable": False, "desc": "Observation/specimen collection timestamp (ISO YYYY-MM-DD)", "ord": 4},
                {"name": "result_value", "type": "DECIMAL", "required": False, "nullable": True, "desc": "Quantitative numerical measurement result", "ord": 5},
                {"name": "units", "type": "STRING", "required": False, "nullable": True, "desc": "Standard units of measure (e.g., mg/dL, mmHg)", "ord": 6},
            ]
        },
    ]

    for m in models_data:
        m_id = m['id']
        m_name = m['name']
        m_domain = m['domain']
        m_desc = m['description'].replace("'", "''")
        op.execute(f"""
            INSERT INTO canonical_models (id, name, domain, description, created_by, updated_by)
            VALUES ('{m_id}'::uuid, '{m_name}', '{m_domain}', '{m_desc}', 'system_seed', 'system_seed')
            ON CONFLICT (name) DO NOTHING;
        """)

        for f in m['fields']:
            f_id = str(uuid.uuid4())
            f_name = f['name']
            f_type = f['type']
            f_req = 'true' if f['required'] else 'false'
            f_null = 'true' if f['nullable'] else 'false'
            f_desc = f['desc'].replace("'", "''")
            f_ord = f['ord']
            op.execute(f"""
                INSERT INTO canonical_fields (id, canonical_model_id, field_name, data_type, is_required, is_nullable, description, ordinal_position, created_by, updated_by)
                VALUES ('{f_id}'::uuid, '{m_id}'::uuid, '{f_name}', '{f_type}'::schema_data_type_enum, {f_req}, {f_null}, '{f_desc}', {f_ord}, 'system_seed', 'system_seed')
                ON CONFLICT (canonical_model_id, field_name) DO NOTHING;
            """)


def downgrade() -> None:
    op.drop_table('mapping_lines')
    op.drop_table('mapping_versions')
    op.drop_table('mappings')
    op.drop_table('canonical_fields')
    op.drop_table('canonical_models')
    op.execute("DROP TYPE IF EXISTS transform_type_enum")
    op.execute("DROP TYPE IF EXISTS mapping_version_status_enum")
