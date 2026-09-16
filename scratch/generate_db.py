import os

MD_PATH = r"d:\Digitalurth\DATABASE_DESIGN.md"

def render_table(t):
    res = f"#### Table: `{t['name']}`\n"
    res += f"**Purpose:** {t['purpose']}\n\n"
    res += "**Columns:**\n"
    res += "| Column | Type | Nullable | Default | Description |\n"
    res += "|---|---|---|---|---|\n"
    res += "| id | UUID | No | gen_random_uuid() | Primary key |\n"
    
    for c in t['cols']:
        res += f"| {c[0]} | {c[1]} | {'Yes' if c[2] else 'No'} | {c[3]} | {c[4]} |\n"
        
    res += "| created_at | timestamptz | No | now() | Creation timestamp |\n"
    res += "| created_by | UUID | Yes | NULL | FK to users.id (nullable for system actions) |\n"
    res += "| updated_at | timestamptz | No | now() | Last update timestamp |\n"
    res += "| updated_by | UUID | Yes | NULL | FK to users.id |\n"
    res += "| version | integer | No | 1 | Optimistic locking |\n\n"
    
    res += f"- **Primary Key:** {t.get('pk', 'id')}\n"
    fks = t.get('fks', [])
    res += "- **Foreign Keys:**\n"
    for fk in fks:
        res += f"  - {fk}\n"
    if not fks: res += "  - None\n"
        
    unique = t.get('unique', [])
    res += "- **Unique Constraints:**\n"
    for u in unique:
        res += f"  - {u}\n"
    if not unique: res += "  - None\n"
    
    idx = t.get('idx', [])
    res += "- **Indexes:**\n"
    for i in idx:
        res += f"  - {i}\n"
    if not idx: res += "  - None\n"
    
    res += f"- **Business Rules:** {t.get('rules', 'Standard audit and optimistic locking apply.')}\n\n"
    return res


domains = [
    {
        "id": 1,
        "name": "Users, Roles & Permissions",
        "diagram": """```mermaid
erDiagram
    users ||--o{ user_roles : has
    roles ||--o{ user_roles : assigned_to
    roles ||--o{ permissions : grants
    roles ||--o{ role_scopes : scoped_by
    users ||--o{ sessions : creates
    users ||--o{ access_reviews : reviewed_in
    users ||--o{ emergency_access_grants : requests
```""",
        "tables": [
            {
                "name": "users", "purpose": "Core user identities mapped to Entra ID.",
                "cols": [
                    ("entra_id", "varchar", False, "''", "Entra ID reference"),
                    ("email", "varchar", False, "''", "User email address"),
                    ("full_name", "varchar", False, "''", "User's full name"),
                    ("is_active", "boolean", False, "true", "Account status")
                ],
                "unique": ["entra_id", "email"],
                "idx": ["idx_users_entra_id", "idx_users_email"]
            },
            {
                "name": "roles", "purpose": "System roles (e.g. Data Steward, BA).",
                "cols": [("name", "varchar", False, "''", "Role name"), ("description", "text", True, "NULL", "Role description")]
            },
            {
                "name": "permissions", "purpose": "Fine-grained system permissions.",
                "cols": [("role_id", "UUID", False, "''", "Role ID"), ("resource", "varchar", False, "''", "Resource name"), ("action", "varchar", False, "''", "Action (read, write)")]
            },
            {
                "name": "user_roles", "purpose": "Mapping of users to roles.",
                "cols": [("user_id", "UUID", False, "''", ""), ("role_id", "UUID", False, "''", "")]
            },
            {
                "name": "role_scopes", "purpose": "Data layer scope enforcement.",
                "cols": [("role_id", "UUID", False, "''", ""), ("scope_type", "varchar", False, "''", "Feed, Source, Domain"), ("scope_value", "varchar", False, "''", "ID of the scope")]
            },
            {
                "name": "sessions", "purpose": "User login sessions.",
                "cols": [("user_id", "UUID", False, "''", ""), ("token_hash", "varchar", False, "''", ""), ("expires_at", "timestamptz", False, "''", "")]
            },
            {
                "name": "access_reviews", "purpose": "Periodic access review campaigns.",
                "cols": [("campaign_name", "varchar", False, "''", ""), ("reviewer_id", "UUID", False, "''", ""), ("status", "varchar", False, "''", "")]
            },
            {
                "name": "emergency_access_grants", "purpose": "Break-glass access records.",
                "cols": [("user_id", "UUID", False, "''", ""), ("reason", "text", False, "''", ""), ("expires_at", "timestamptz", False, "''", "")]
            }
        ]
    },
    {
        "id": 2, "name": "Execution-Plane Contract Register",
        "diagram": "```mermaid\nerDiagram\n    contract_register_entries ||--o{ contract_unknowns : tracks\n    contract_register_entries ||--o{ contract_story_links : links\n```",
        "tables": [
            {"name": "contract_register_entries", "purpose": "Tracks API/control table reads and writes per feature.", "cols": [("feature_name", "varchar", False, "''", "")]},
            {"name": "contract_unknowns", "purpose": "Unconfirmed facts about production.", "cols": [("entry_id", "UUID", False, "''", ""), ("description", "text", False, "''", ""), ("confirmed", "boolean", False, "false", "")]},
            {"name": "contract_story_links", "purpose": "Jira story links to contracts.", "cols": [("entry_id", "UUID", False, "''", ""), ("story_id", "varchar", False, "''", "")]}
        ]
    },
    {
        "id": 3, "name": "Source & Feed Registry",
        "diagram": "```mermaid\nerDiagram\n    sources ||--o{ feeds : owns\n    feeds ||--o{ feed_versions : has\n    feeds ||--o{ feed_documents : documents\n    feeds ||--o{ feed_dependencies : depends_on\n```",
        "tables": [
            {"name": "sources", "purpose": "External source organizations.", "cols": [("name", "varchar", False, "''", "")]},
            {"name": "feeds", "purpose": "Data feeds from sources.", "cols": [("source_id", "UUID", False, "''", ""), ("name", "varchar", False, "''", ""), ("status", "varchar", False, "''", "lifecycle_state")]},
            {"name": "feed_versions", "purpose": "Versioning of feed configurations.", "cols": [("feed_id", "UUID", False, "''", ""), ("config_json", "jsonb", False, "''", "")]},
            {"name": "feed_documents", "purpose": "Attached specs.", "cols": [("feed_id", "UUID", False, "''", ""), ("doc_url", "varchar", False, "''", "")]},
            {"name": "feed_dependencies", "purpose": "Upstream/downstream feed links.", "cols": [("feed_id", "UUID", False, "''", ""), ("depends_on_feed_id", "UUID", False, "''", "")]}
        ]
    },
    {
        "id": 4, "name": "Schema Contracts & Profiling",
        "diagram": "```mermaid\nerDiagram\n    schemas ||--o{ schema_versions : versions\n    schema_versions ||--o{ schema_fields : contains\n    schemas ||--o{ profiling_runs : profiled_by\n```",
        "tables": [
            {"name": "schemas", "purpose": "Logical schemas for feeds.", "cols": [("feed_id", "UUID", False, "''", "")]},
            {"name": "schema_versions", "purpose": "Schema contract versions.", "cols": [("schema_id", "UUID", False, "''", ""), ("status", "varchar", False, "''", "lifecycle_state")]},
            {"name": "schema_fields", "purpose": "Individual fields in a schema.", "cols": [("schema_version_id", "UUID", False, "''", ""), ("name", "varchar", False, "''", ""), ("data_type", "varchar", False, "''", "")]},
            {"name": "profiling_runs", "purpose": "AI/Statistical profiling runs.", "cols": [("feed_id", "UUID", False, "''", ""), ("status", "varchar", False, "''", "")]},
            {"name": "profiling_results", "purpose": "Column-level profiling stats.", "cols": [("run_id", "UUID", False, "''", ""), ("field_name", "varchar", False, "''", "")]},
            {"name": "phi_classifications", "purpose": "PHI flags per field.", "cols": [("field_id", "UUID", False, "''", ""), ("phi_type", "varchar", False, "''", "")]}
        ]
    },
    {
        "id": 5, "name": "Canonical Mapping",
        "diagram": "```mermaid\nerDiagram\n    canonical_model_entities ||--o{ canonical_model_fields : has\n    mappings ||--o{ mapping_versions : versions\n    mapping_versions ||--o{ mapping_lines : lines\n    mapping_lines ||--o{ mapping_transforms : transforms\n```",
        "tables": [
            {"name": "canonical_model_entities", "purpose": "Target canonical tables.", "cols": [("name", "varchar", False, "''", "")]},
            {"name": "canonical_model_fields", "purpose": "Target fields in canonical model.", "cols": [("entity_id", "UUID", False, "''", ""), ("name", "varchar", False, "''", "")]},
            {"name": "mappings", "purpose": "Source to target mapping documents.", "cols": [("feed_id", "UUID", False, "''", "")]},
            {"name": "mapping_versions", "purpose": "Versioned mappings.", "cols": [("mapping_id", "UUID", False, "''", ""), ("status", "varchar", False, "''", "lifecycle_state")]},
            {"name": "mapping_lines", "purpose": "Individual column mappings.", "cols": [("mapping_version_id", "UUID", False, "''", ""), ("source_field", "varchar", False, "''", ""), ("target_field_id", "UUID", False, "''", "")]},
            {"name": "mapping_transforms", "purpose": "Transform logic per mapping line.", "cols": [("line_id", "UUID", False, "''", ""), ("transform_type", "varchar", False, "''", "")]}
        ]
    },
    {
        "id": 6, "name": "Data Quality Rules",
        "diagram": "```mermaid\nerDiagram\n    rules ||--o{ rule_versions : versions\n    rule_versions ||--o{ rule_test_runs : tests\n```",
        "tables": [
            {"name": "rules", "purpose": "DQ Rules.", "cols": [("feed_id", "UUID", False, "''", "")]},
            {"name": "rule_versions", "purpose": "Versioned rules.", "cols": [("rule_id", "UUID", False, "''", ""), ("logic_sql", "text", False, "''", ""), ("severity", "varchar", False, "''", "severity_level")]},
            {"name": "rule_test_runs", "purpose": "Rule test execution records.", "cols": [("rule_version_id", "UUID", False, "''", "")]},
            {"name": "rule_test_results", "purpose": "Test outcomes.", "cols": [("run_id", "UUID", False, "''", "")]},
            {"name": "rule_execution_results", "purpose": "Production execution outcomes.", "cols": [("rule_version_id", "UUID", False, "''", ""), ("batch_id", "UUID", False, "''", "")]}
        ]
    },
    {
        "id": 7, "name": "Pipeline Execution",
        "diagram": "```mermaid\nerDiagram\n    batches ||--o{ batch_stages : stages\n    batches ||--o{ quarantine_records : isolates\n```",
        "tables": [
            {"name": "batches", "purpose": "Execution batches.", "cols": [("feed_id", "UUID", False, "''", ""), ("status", "varchar", False, "''", "batch_status")]},
            {"name": "batch_stages", "purpose": "Stages per batch.", "cols": [("batch_id", "UUID", False, "''", ""), ("stage_name", "varchar", False, "''", "stage_name")]},
            {"name": "input_registry", "purpose": "Arriving file registry.", "cols": [("file_name", "varchar", False, "''", ""), ("hash", "varchar", False, "''", "")]},
            {"name": "quarantine_records", "purpose": "Isolated bad rows.", "cols": [("batch_id", "UUID", False, "''", ""), ("raw_payload", "jsonb", False, "''", "")]}
        ]
    },
    {
        "id": 8, "name": "Reconciliation & Certification",
        "diagram": "```mermaid\nerDiagram\n    batch_reconciliation ||--o{ reconciliation_ledger_entries : ledgers\n    batch_reconciliation ||--o{ variances : finds\n```",
        "tables": [
            {"name": "batch_reconciliation", "purpose": "Reconciliation summary per batch.", "cols": [("batch_id", "UUID", False, "''", "")]},
            {"name": "reconciliation_ledger_entries", "purpose": "Line items for dropped rows.", "cols": [("recon_id", "UUID", False, "''", "")]},
            {"name": "variances", "purpose": "Reconciliation mismatches.", "cols": [("recon_id", "UUID", False, "''", "")]},
            {"name": "variance_investigations", "purpose": "Investigation workflows.", "cols": [("variance_id", "UUID", False, "''", "")]},
            {"name": "batch_certifications", "purpose": "Final batch certifications.", "cols": [("batch_id", "UUID", False, "''", "")]},
            {"name": "waivers", "purpose": "Approved waivers for variances.", "cols": [("variance_id", "UUID", False, "''", "")]}
        ]
    },
    {
        "id": 9, "name": "Workflow & Approvals",
        "diagram": "```mermaid\nerDiagram\n    approval_requests ||--o{ approval_decisions : decisions\n```",
        "tables": [
            {"name": "lifecycle_transitions", "purpose": "State transition audit.", "cols": [("entity_type", "varchar", False, "''", ""), ("entity_id", "UUID", False, "''", "")]},
            {"name": "approval_requests", "purpose": "Requests for state change.", "cols": [("entity_id", "UUID", False, "''", "")]},
            {"name": "approval_decisions", "purpose": "Approver decisions.", "cols": [("request_id", "UUID", False, "''", ""), ("decision", "varchar", False, "''", "")]},
            {"name": "approval_comments", "purpose": "Comments on requests.", "cols": [("request_id", "UUID", False, "''", "")]}
        ]
    },
    {
        "id": 10, "name": "Scheduling",
        "diagram": "```mermaid\nerDiagram\n    schedules ||--o{ schedule_dependencies : dependencies\n```",
        "tables": [
            {"name": "schedules", "purpose": "Execution schedules.", "cols": [("feed_id", "UUID", False, "''", ""), ("cron_expr", "varchar", False, "''", "")]},
            {"name": "schedule_dependencies", "purpose": "Wait-for relationships.", "cols": [("schedule_id", "UUID", False, "''", "")]},
            {"name": "schedule_runs", "purpose": "Triggered schedule runs.", "cols": [("schedule_id", "UUID", False, "''", "")]}
        ]
    },
    {
        "id": 11, "name": "Operations & Incidents",
        "diagram": "```mermaid\nerDiagram\n    incidents ||--o{ incident_assignments : assignments\n```",
        "tables": [
            {"name": "incidents", "purpose": "Operational incidents.", "cols": [("status", "varchar", False, "''", "")]},
            {"name": "incident_assignments", "purpose": "Staff assignments.", "cols": [("incident_id", "UUID", False, "''", "")]},
            {"name": "incident_notes", "purpose": "Investigation notes.", "cols": [("incident_id", "UUID", False, "''", "")]},
            {"name": "failure_fingerprints", "purpose": "AI failure signatures.", "cols": [("signature_hash", "varchar", False, "''", "")]},
            {"name": "recovery_guides", "purpose": "Runbooks for known failures.", "cols": [("fingerprint_id", "UUID", False, "''", "")]},
            {"name": "alert_enrichments", "purpose": "Context added to alerts.", "cols": [("incident_id", "UUID", False, "''", "")]}
        ]
    },
    {
        "id": 12, "name": "Identity Resolution",
        "diagram": "```mermaid\nerDiagram\n    identity_requests ||--o{ identity_responses : responses\n```",
        "tables": [
            {"name": "identity_requests", "purpose": "Requests sent to Verato.", "cols": [("batch_id", "UUID", False, "''", "")]},
            {"name": "identity_responses", "purpose": "Responses from Verato.", "cols": [("request_id", "UUID", False, "''", "")]},
            {"name": "crosswalk", "purpose": "Source ID to LinkID mapping.", "cols": [("source_id", "varchar", False, "''", ""), ("link_id", "varchar", False, "''", "")]},
            {"name": "identity_exceptions", "purpose": "Unresolved identities.", "cols": [("batch_id", "UUID", False, "''", "")]},
            {"name": "merge_split_decisions", "purpose": "Steward identity actions.", "cols": [("link_id", "varchar", False, "''", "")]}
        ]
    },
    {
        "id": 13, "name": "Silver ODS",
        "diagram": "```mermaid\nerDiagram\n    ods_model_versions ||--o{ ods_entity_definitions : defines\n```",
        "tables": [
            {"name": "ods_model_versions", "purpose": "ODS schema versions.", "cols": [("version_tag", "varchar", False, "''", "")]},
            {"name": "ods_entity_definitions", "purpose": "ODS tables.", "cols": [("model_version_id", "UUID", False, "''", "")]},
            {"name": "ods_field_definitions", "purpose": "ODS columns.", "cols": [("entity_id", "UUID", False, "''", "")]},
            {"name": "ods_certifications", "purpose": "Data release certifications.", "cols": [("batch_id", "UUID", False, "''", "")]},
            {"name": "consumer_registrations", "purpose": "Downstream consumers.", "cols": [("system_name", "varchar", False, "''", "")]}
        ]
    },
    {
        "id": 14, "name": "Catalog & Glossary",
        "diagram": "```mermaid\nerDiagram\n    glossary_terms ||--o{ glossary_term_versions : versions\n```",
        "tables": [
            {"name": "glossary_terms", "purpose": "Business dictionary.", "cols": [("term", "varchar", False, "''", "")]},
            {"name": "glossary_term_versions", "purpose": "Definitions.", "cols": [("term_id", "UUID", False, "''", "")]},
            {"name": "catalog_entries", "purpose": "Data catalog items.", "cols": [("entity_type", "varchar", False, "''", "")]},
            {"name": "catalog_lineage", "purpose": "Data lineage links.", "cols": [("source_entry_id", "UUID", False, "''", "")]},
            {"name": "knowledge_articles", "purpose": "Runbooks and FAQs.", "cols": [("title", "varchar", False, "''", "")]},
            {"name": "knowledge_article_versions", "purpose": "Article revisions.", "cols": [("article_id", "UUID", False, "''", "")]}
        ]
    },
    {
        "id": 15, "name": "Releases",
        "diagram": "```mermaid\nerDiagram\n    releases ||--o{ release_items : contains\n```",
        "tables": [
            {"name": "releases", "purpose": "Configuration deployments.", "cols": [("release_tag", "varchar", False, "''", "")]},
            {"name": "release_items", "purpose": "Configs in a release.", "cols": [("release_id", "UUID", False, "''", "")]},
            {"name": "release_windows", "purpose": "Allowed deployment times.", "cols": [("start_time", "timestamptz", False, "''", "")]},
            {"name": "freeze_periods", "purpose": "No-deploy windows.", "cols": [("start_time", "timestamptz", False, "''", "")]},
            {"name": "rollback_records", "purpose": "Deployment reversions.", "cols": [("release_id", "UUID", False, "''", "")]}
        ]
    },
    {
        "id": 16, "name": "Migration",
        "diagram": "```mermaid\nerDiagram\n    migration_waves ||--o{ migration_wave_feeds : schedules\n```",
        "tables": [
            {"name": "migration_feeds", "purpose": "Legacy feeds tracking.", "cols": [("legacy_name", "varchar", False, "''", "")]},
            {"name": "migration_waves", "purpose": "Rollout phases.", "cols": [("wave_number", "integer", False, "''", "")]},
            {"name": "migration_wave_feeds", "purpose": "Feeds in a wave.", "cols": [("wave_id", "UUID", False, "''", "")]},
            {"name": "migration_evidence", "purpose": "Cutover readiness proofs.", "cols": [("feed_id", "UUID", False, "''", "")]},
            {"name": "migration_comparisons", "purpose": "Parallel run stats.", "cols": [("feed_id", "UUID", False, "''", "")]},
            {"name": "migration_cutover_checklists", "purpose": "Go-live steps.", "cols": [("wave_id", "UUID", False, "''", "")]},
            {"name": "ownership_transfers", "purpose": "Artifact handoffs.", "cols": [("artifact_name", "varchar", False, "''", "")]}
        ]
    },
    {
        "id": 17, "name": "Audit",
        "diagram": "```mermaid\nerDiagram\n    audit_events ||--o{ audit_events : tracks\n```",
        "tables": [
            {"name": "audit_events", "purpose": "Immutable log of all changes.", "cols": [("table_name", "varchar", False, "''", ""), ("record_id", "UUID", False, "''", ""), ("action", "varchar", False, "''", ""), ("old_data", "jsonb", True, "NULL", ""), ("new_data", "jsonb", True, "NULL", "")]}
        ]
    }
]

md = "# CINQFLOW Database Design\n\n"
md += "This document specifies the comprehensive PostgreSQL 16+ schema designed for the CINQFLOW healthcare data platform. The schema aligns with all Epic and Wave requirements, supporting metadata-driven execution, rigid role-based access, automated lineage, and auditable governance workflows.\n\n"

md += "## Cross-Domain Relationship Summary\n"
md += "The core entity is `feeds`, connected to practically every operational aspect (mappings, schemas, schedules, runs). The system maintains an append-only architectural posture via immutable version tables and a centralized `audit_events` ledger. The metadata definition tables directly govern pipeline generation.\n\n"

md += "## Enum Types\n"
md += "```sql\n"
md += "CREATE TYPE lifecycle_state AS ENUM ('Draft', 'In Review', 'Approved', 'Published', 'Retired');\n"
md += "CREATE TYPE batch_status AS ENUM ('Pending', 'In Progress', 'Completed', 'Failed', 'Failed-Reconciliation', 'Waiting-on-Upstream');\n"
md += "CREATE TYPE stage_name AS ENUM ('Landing', 'Bronze', 'Silver Raw', 'Identity', 'Silver ODS');\n"
md += "CREATE TYPE severity_level AS ENUM ('Information', 'Warning', 'Manual review', 'Quarantine', 'Reject', 'Stop pipeline');\n"
md += "CREATE TYPE phi_classification AS ENUM ('Non-PHI', 'PHI-Direct', 'PHI-Indirect');\n"
md += "```\n\n"

md += "## Migration Strategy Notes\n"
md += "- **Alembic Usage**: All primary keys are `UUID` generated via `gen_random_uuid()` for compatibility with Postgres 16.\n"
md += "- **Audit Columns**: Defined as an Alembic base mixin `AuditMixin` applied to every declarative base class.\n"
md += "- **Immutability**: Historical records are never UPDATEd or DELETEd directly, enforced via triggers and ORM layers. Optimistic locking requires `version` to increment on update.\n\n"


for d in domains:
    md += f"### Domain {d['id']}: {d['name']}\n\n"
    md += d['diagram'] + "\n\n"
    for t in d['tables']:
        md += render_table(t)

with open(MD_PATH, 'w') as f:
    f.write(md)
    
print("Successfully wrote database design to " + MD_PATH)
