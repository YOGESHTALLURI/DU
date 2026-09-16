# CINQFLOW Requirements Traceability Matrix

## Wave 0: MVP End-to-End Pipeline
| Story ID | Requirement | Technical Module | API Endpoints | Database Tables | UI Screen(s) | Worker/Service | Test Type(s) | Wave | Status |
|----------|-------------|------------------|---------------|-----------------|--------------|----------------|--------------|------|--------|
| CF-V0-E1-01 | Execution-Plane Contract Register | `contract` | `POST /api/v1/contracts` | `contract_register_entries`, `contract_unknowns` | Contract Form | Contract Service | Unit, Integration, E2E | 0 | Not Started |
| CF-V0-E2-01 | Sign-in with AuthProvider (MockAuthProvider dev, EntraAuthProvider prod) and Basic Roles | `auth` | `POST /api/v1/auth/login`, `GET /api/v1/auth/me` | `users`, `roles`, `user_roles`, `sessions` | Login Screen | Auth Service (AuthProvider interface) | Unit, Integration, E2E | 0 | Not Started |
| CF-V0-E3-01 | Minimal Feed Record the Engine Can Run From | `registry` | `POST /api/v1/feeds`, `GET /api/v1/feeds` | `feeds`, `feed_versions` | Feed Registry | Registry Service | Unit, Integration | 0 | Not Started |
| CF-V0-E8-01 | Pipeline Compiler — Landing to Bronze to Silver Raw (NO ODS) | `engine` | `POST /api/v1/pipeline/execute`, `GET /api/v1/pipeline/batches/{id}` | `batches`, `batch_stages`, `quarantine_records` | Pipeline Dashboard | Pipeline Engine (Celery) | Unit, Integration, E2E, Idempotency | 0 | Not Started |
| CF-V0-E8-02 | Landing Zone Controls — Register, Validate, Fingerprint, Reject Duplicates | `landing` | `POST /api/v1/inputs/register`, `GET /api/v1/inputs` | `input_registry` | Landing View | Landing Worker | Unit, Integration, Idempotency | 0 | Not Started |
| CF-V0-E13-01 | Count Reconciliation with Named-Reason Drop Ledger | `reconciliation` | `GET /api/v1/reconciliation/batches/{batchId}` | `batch_reconciliation`, `reconciliation_ledger_entries` | Reconciliation View | Recon Service | Unit, Integration, Reconciliation | 0 | Not Started |

## Wave 1: Analyst Build Path
| Story ID | Requirement | Technical Module | API Endpoints | Database Tables | UI Screen(s) | Worker/Service | Test Type(s) | Wave | Status |
|----------|-------------|------------------|---------------|-----------------|--------------|----------------|--------------|------|--------|
| CF-V1-E3-02 | Full Source and Feed Registry | `registry` | `PUT /api/v1/feeds/{id}` | `sources`, `feeds` | Feed Setup | Registry Service | Unit, E2E | 1 | Not Started |
| CF-V1-E3-03 | Clone a Similar Feed | `registry` | `POST /api/v1/feeds/clone` | `feeds`, `feed_versions` | Clone Feed | Registry Service | Unit, Integration | 1 | Not Started |
| CF-V1-E3-04 | Feed Lifecycle, Version History | `registry` | `GET /api/v1/feeds/{id}/versions` | `feed_versions` | Feed History | Registry Service | Unit, Integration | 1 | Not Started |
| CF-V1-E4-01 | The Five-Step Onboarding Wizard | `onboarding` | `GET /api/v1/onboarding/status` | `feeds` | Wizard UI | Onboarding Service | Unit, E2E | 1 | Not Started |
| CF-V1-E4-02 | End-to-End Sample Test | `onboarding` | `POST /api/v1/onboarding/test` | `batch_stages` | E2E Test View | Engine Worker | Integration | 1 | Not Started |
| CF-V1-E4-03 | Submit, Approve, Publish | `onboarding` | `POST /api/v1/approvals` | `approval_requests` | Approval Queue | Approval Service | Unit, Integration | 1 | Not Started |
| CF-V1-E5-01 | Deterministic File Profiler | `profiler` | `POST /api/v1/profiler/run` | `schema_fields` | Profiling Dashboard | Profiler Worker | Unit, Integration | 1 | Not Started |
| CF-V1-E5-02 | AI Schema Inference into an Approved Data Contract | `ai` | `POST /api/v1/ai/schema` | `schemas`, `schema_versions` | Schema Builder | AI Service | Unit, E2E | 1 | Not Started |
| CF-V1-E5-03 | PHI and Healthcare Code-Set Detection | `ai` | `POST /api/v1/ai/phi-detect` | `schema_fields` | PHI Config | AI Service | Unit, Integration | 1 | Not Started |
| CF-V1-E6-01 | Canonical Model Browser | `mapping` | `GET /api/v1/mappings/models` | `mappings` | Model Browser | Mapping Service | Unit | 1 | Not Started |
| CF-V1-E6-02 | AI Mapping Suggestions with Confidence | `ai` | `POST /api/v1/ai/mapping` | `mapping_lines` | AI Suggestions | AI Service | Unit, E2E | 1 | Not Started |
| CF-V1-E6-03 | Manual Mapping Editor with Full Transform Toolbox | `mapping` | `PUT /api/v1/mappings` | `mapping_versions` | Mapping Studio | Mapping Service | Unit, E2E | 1 | Not Started |
| CF-V1-E6-04 | Mapping Approval, Versioning and Impact Analysis | `mapping` | `GET /api/v1/mappings/impact` | `mapping_versions` | Impact View | Mapping Service | Integration | 1 | Not Started |
| CF-V1-E7-01 | Write a Data Rule in Plain English | `ai` | `POST /api/v1/ai/rules` | `rules` | Rules Editor | AI Service | Unit, E2E | 1 | Not Started |
| CF-V1-E7-02 | Test a Rule on Real Sample Data | `rules` | `POST /api/v1/rules/test` | `rule_test_results` | Rule Tester | Rules Engine | Integration | 1 | Not Started |
| CF-V1-E7-03 | Rule Severity, Layer and Threshold Configuration | `rules` | `PUT /api/v1/rules/config` | `rule_versions` | Rule Settings | Rules Service | Unit | 1 | Not Started |
| CF-V1-E7-04 | Low-Confidence and Unsupported Rules Go to Technical Review | `rules` | `POST /api/v1/rules/review` | `rule_versions` | Tech Review Queue | Rules Service | Integration | 1 | Not Started |
| CF-V1-E8-03 | Scheduling, Dependencies and Downstream Protection | `scheduling` | `POST /api/v1/schedules` | `schedules` | Scheduler View | Orchestration Service| Unit, E2E | 1 | Not Started |
| CF-V1-E11-01 | One Lifecycle Engine for Every Governed Object | `lifecycle` | `POST /api/v1/lifecycle/transition` | `approval_decisions` | Lifecycle Tracker | Lifecycle Service | Unit, E2E | 1 | Not Started |
| CF-V1-E11-02 | Approval Packet with Both-Sides Impact | `approval` | `GET /api/v1/approvals/packet` | `approval_requests` | Packet View | Approval Service | Unit, Integration | 1 | Not Started |
| CF-V1-E14-01 | Business Glossary Service | `glossary` | `GET /api/v1/glossary` | `glossary_terms` | Glossary View | Glossary Service | Unit | 1 | Not Started |

## Wave 2: Operations and Reliability
| Story ID | Requirement | Technical Module | API Endpoints | Database Tables | UI Screen(s) | Worker/Service | Test Type(s) | Wave | Status |
|----------|-------------|------------------|---------------|-----------------|--------------|----------------|--------------|------|--------|
| CF-V2-E5-04 | Schema Drift Detection | `schema` | `GET /api/v1/schemas/drift` | `schema_versions` | Drift Alert | Profiler Worker | Integration | 2 | Not Started |
| CF-V2-E7-05 | Rules Running in Production | `rules` | `GET /api/v1/rules/executions` | `dq_results` | DQ Dashboard | Rules Engine | Unit, E2E | 2 | Not Started |
| CF-V2-E8-04 | Recovery Operations — Restart, Reprocess | `operations` | `POST /api/v1/ops/recover` | `batch_stages` | Recovery View | Ops Service | Integration | 2 | Not Started |
| CF-V2-E12-01 | Data Operations Home and File-Arrival Board | `operations` | `GET /api/v1/ops/home` | `batches` | Ops Home | Ops Service | Unit | 2 | Not Started |
| CF-V2-E12-02 | Batch and Stage Monitor | `operations` | `GET /api/v1/ops/monitor` | `batch_stages` | Stage Monitor | Ops Service | Unit, Integration | 2 | Not Started |
| CF-V2-E12-03 | Governed Action Surface | `operations` | `POST /api/v1/ops/actions` | `audit_events` | Action Modal | Ops Worker | Integration | 2 | Not Started |
| CF-V2-E12-04 | Failure Fingerprinting and Recovery-Guide Matching | `incidents` | `POST /api/v1/incidents/match` | `failure_fingerprints` | Incident View | AI Service | Integration | 2 | Not Started |
| CF-V2-E12-05 | Alerts That Explain Themselves | `alerts` | `POST /api/v1/alerts/enrich` | `incidents` | Alert View | Alert Worker | Integration | 2 | Not Started |
| CF-V2-E13-03 | Variance Investigation, Approval and Waiver | `reconciliation`| `POST /api/v1/reconciliation/variance` | `batch_reconciliation` | Variance Queue | Recon Service | Unit, E2E | 2 | Not Started |
| CF-V2-E13-04 | Data Certification | `reconciliation`| `POST /api/v1/reconciliation/certify` | `ods_certifications` | Certification View| Recon Service | Integration | 2 | Not Started |

## Wave 3: Identity and Canonical ODS
| Story ID | Requirement | Technical Module | API Endpoints | Database Tables | UI Screen(s) | Worker/Service | Test Type(s) | Wave | Status |
|----------|-------------|------------------|---------------|-----------------|--------------|----------------|--------------|------|--------|
| CF-V3-E5-05 | Profiling for Complex Formats | `profiler` | `POST /api/v1/profiler/complex` | `schema_fields` | Profiler Dashboard| Profiler Worker | Integration | 3 | Not Started |
| CF-V3-E6-05 | Structural Transforms for Complex Formats | `mapping` | `PUT /api/v1/mappings/transforms`| `mapping_lines` | Transform Studio | Mapping Service | Unit, E2E | 3 | Not Started |
| CF-V3-E8-05 | Silver Raw to Silver ODS Stage | `engine` | `POST /api/v1/engine/ods-stage` | `batch_stages` | Pipeline View | Pipeline Engine | Integration | 3 | Not Started |
| CF-V3-E9-01 | Verato Identity Stage in the Pipeline | `identity` | `POST /api/v1/identity/resolve` | `identity_requests` | Identity View | Identity Service | E2E | 3 | Not Started |
| CF-V3-E9-02 | Identity Exception Queue | `identity` | `GET /api/v1/identity/exceptions`| `identity_responses`| Exception Queue | Identity Service | Unit, E2E | 3 | Not Started |
| CF-V3-E9-03 | Merge and Split Decisions | `ai` | `POST /api/v1/identity/merge` | `crosswalk` | Decision UI | AI Service | Unit, E2E | 3 | Not Started |
| CF-V3-E9-04 | Identity Reconciliation and Cutover Telemetry | `identity` | `GET /api/v1/identity/telemetry` | `crosswalk` | Telemetry Dashboard| Identity Service | Integration | 3 | Not Started |
| CF-V3-E10-01| Deploy the Canonical ODS Model | `ods` | `POST /api/v1/ods/deploy` | `ods_model_versions`| Model Viewer | ODS Worker | E2E | 3 | Not Started |
| CF-V3-E10-02| Model Versions and Downstream Data Contract | `ods` | `GET /api/v1/ods/versions` | `ods_model_versions`| Contract View | ODS Service | Unit | 3 | Not Started |
| CF-V3-E10-03| ODS Certification and Consumer Compatibility Gate | `ods` | `POST /api/v1/ods/certify` | `ods_certifications`| Certify View | ODS Service | Integration | 3 | Not Started |
| CF-V3-E13-02| Financial and Member Reconciliation | `reconciliation`| `GET /api/v1/reconciliation/fin` | `batch_reconciliation`| Recon Dashboard | Recon Service | Integration | 3 | Not Started |

## Wave 4: Scale, Security, and Self-Service
| Story ID | Requirement | Technical Module | API Endpoints | Database Tables | UI Screen(s) | Worker/Service | Test Type(s) | Wave | Status |
|----------|-------------|------------------|---------------|-----------------|--------------|----------------|--------------|------|--------|
| CF-V4-E2-02 | Full Role Matrix with Source, Feed, Domain | `auth` | `GET /api/v1/auth/roles` | `role_scopes` | Role Management | Auth Service | Unit, E2E | 4 | Not Started |
| CF-V4-E2-03 | PHI Masking Everywhere and Export Control | `phi` | `GET /api/v1/phi/export` | `users` | Export Settings | PHI Service | Unit, Integration | 4 | Not Started |
| CF-V4-E2-04 | Audit Trail, Access Review and Emergency Access | `audit` | `GET /api/v1/audit/logs` | `audit_events` | Audit Log | Audit Service | Integration | 4 | Not Started |
| CF-V4-E4-04 | Onboarding Templates and Similar-Feed Suggestions | `onboarding` | `GET /api/v1/onboarding/templates`| `feeds` | Wizard Templates | Onboarding Service| Unit, E2E | 4 | Not Started |
| CF-V4-E8-06 | Configuration Promotion Through Environments | `releases` | `POST /api/v1/releases/promote` | `releases` | Release Manager | Release Worker | E2E | 4 | Not Started |
| CF-V4-E11-03| Release Management — Windows, Freeze, History | `releases` | `GET /api/v1/releases/history` | `release_items` | Release History | Release Service | Integration | 4 | Not Started |
| CF-V4-E11-04| Emergency Change and Pause Workflow | `releases` | `POST /api/v1/releases/emergency`| `audit_events` | Emergency Console | Release Service | E2E | 4 | Not Started |
| CF-V4-E14-02| Data Catalog | `catalog` | `GET /api/v1/catalog` | `catalog_entries` | Catalog Browser | Catalog Service | Unit | 4 | Not Started |
| CF-V4-E14-03| Knowledge Base | `knowledge` | `GET /api/v1/knowledge` | `knowledge_articles`| KB Viewer | Knowledge Service | Unit | 4 | Not Started |
| CF-V4-E14-04| Copilot Assistant | `copilot` | `POST /api/v1/copilot/ask` | `knowledge_articles`| Chat Interface | AI Service | Integration | 4 | Not Started |

## Wave 5: Migration and Cutover
| Story ID | Requirement | Technical Module | API Endpoints | Database Tables | UI Screen(s) | Worker/Service | Test Type(s) | Wave | Status |
|----------|-------------|------------------|---------------|-----------------|--------------|----------------|--------------|------|--------|
| CF-V5-E1-02 | Incumbent Configuration Harvester | `ai` | `POST /api/v1/migration/harvest` | `migration_feeds` | Harvester UI | AI Service | Integration | 5 | Not Started |
| CF-V5-E1-03 | Feed Inventory and Migration Wave Register | `migration` | `GET /api/v1/migration/inventory` | `migration_waves` | Inventory Board | Migration Service | Unit | 5 | Not Started |
| CF-V5-E1-04 | Validate Inventory Against Production Reality | `migration` | `POST /api/v1/migration/validate` | `migration_evidence`| Validation View | Migration Worker | Integration | 5 | Not Started |
| CF-V5-E15-01| Parallel Run Data Validation | `migration` | `POST /api/v1/migration/parallel` | `migration_evidence`| Parallel Run View | Recon Service | E2E | 5 | Not Started |
| CF-V5-E15-02| Migration Issue Tracking | `migration` | `GET /api/v1/migration/issues` | `incidents` | Migration Board | Migration Service | Unit | 5 | Not Started |
| CF-V5-E15-03| Migration Wave Sign-off | `migration` | `POST /api/v1/migration/signoff` | `approval_requests` | Sign-off Queue | Approval Service | Integration | 5 | Not Started |
| CF-V5-E15-04| Cutover Execution | `migration` | `POST /api/v1/migration/cutover` | `migration_waves` | Cutover Console | Ops Worker | E2E | 5 | Not Started |
