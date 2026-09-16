# CINQFLOW Unknowns and Integration Register

This document serves as the comprehensive register of ALL production dependencies, external systems, and environmental configurations that cannot be confirmed from the requirements document alone. It fulfills the objectives of Epic 1 (specifically `CF-V0-E1-01`), ensuring that assumptions are recorded as data rather than hidden dependencies.

## Risk Matrix Summary

| ID | Category | What is Unknown | Risk Level | Status |
|----|----------|-----------------|------------|--------|
| UNK-001 | Infrastructure | Databricks workspace configuration | Critical | Unconfirmed |
| UNK-002 | Infrastructure | Databricks control table DDL | Critical | Unconfirmed |
| UNK-006 | Infrastructure | VDI/environment access | Critical | Unconfirmed (Blocker) |
| UNK-007 | Infrastructure | Database environment access | Critical | Unconfirmed (Blocker) |
| UNK-010 | Integration | Microsoft Entra ID configuration | Critical | Unconfirmed |
| UNK-021 | Security | Data residency requirements | Critical | Unconfirmed |
| UNK-029 | Deployment | Target deployment platform | Critical | Unconfirmed |
| UNK-003 | Infrastructure | Cloud storage configuration | High | Unconfirmed |
| UNK-004 | Infrastructure | Airflow configuration | High | Unconfirmed |
| UNK-005 | Infrastructure | Network topology | High | Unconfirmed |
| UNK-008 | Integration | Verato API specification | High | Unconfirmed |
| UNK-011 | Integration | LLM provider | High | Unconfirmed |
| UNK-014 | Data | Existing feed inventory | High | Unconfirmed |
| UNK-015 | Data | Canonical model workbooks | High | Unconfirmed |
| UNK-019 | Data | Sample files for each feed type | High | Unconfirmed |
| UNK-020 | Security | PHI handling policy | High | Unconfirmed |
| UNK-022 | Security | AI data processing policy | High | Unconfirmed |
| UNK-025 | Process | Approval routing rules | High | Unconfirmed |
| UNK-009 | Integration | Enterprise notification infrastructure | Medium | Unconfirmed |
| UNK-012 | Integration | Legacy SQL Server database | Medium | Unconfirmed |
| UNK-013 | Integration | SFTP/file transfer infrastructure | Medium | Unconfirmed |
| UNK-016 | Data | Business glossary source | Medium | Unconfirmed |
| UNK-017 | Data | Incumbent GitHub repository structure | Medium | Unconfirmed |
| UNK-018 | Data | Reference data / lookup tables | Medium | Unconfirmed |
| UNK-023 | Security | Audit retention policy | Medium | Unconfirmed |
| UNK-024 | Security | Break-glass / emergency access policy | Medium | Unconfirmed |
| UNK-026 | Process | SLA definitions per feed | Medium | Unconfirmed |
| UNK-027 | Process | Release window schedule | Medium | Unconfirmed |
| UNK-028 | Process | Escalation chains | Medium | Unconfirmed |
| UNK-030 | Deployment | CI/CD pipeline | Medium | Unconfirmed |
| UNK-032 | Deployment | SSL/TLS certificate management | Medium | Unconfirmed |
| UNK-031 | Deployment | Container registry | Low | Unconfirmed |
| UNK-033 | Deployment | DNS and domain configuration | Low | Unconfirmed |

## Recommended Confirmation Priority Order

1. **Immediate Execution Blockers**: UNK-006 (VDI) and UNK-007 (DB access). Development cannot proceed to E2E testing without these.
2. **Identity & Access Floor**: UNK-010 (Entra ID). Required for all user stories involving roles/RBAC (Epic 2).
3. **Core Data Pipeline Backbone**: UNK-001 (Databricks), UNK-002 (Control Tables), and UNK-003 (Storage).
4. **Data Definitions**: UNK-015 (Canonical Model), UNK-019 (Sample Files), and UNK-020 (PHI Handling). Without these, mapping and rule inference work cannot happen.
5. **Infrastructure & Networking**: UNK-005 (Topology), UNK-029 (Deployment Platform).
6. **Integrations**: UNK-008 (Verato API), UNK-011 (LLM Provider).
7. **Remaining Unconfirmed Items**: Escalation, specific deployment toolchains, retention policies.

---

## Detailed Unknowns Register

### Infrastructure Unknowns

#### UNK-001: Databricks workspace configuration
*   **Category**: Infrastructure
*   **What is Unknown**: Cluster types, compute policies, Unity Catalog setup, runtime version, workspace URL, token management.
*   **Which Stories Depend on It**: `CF-V0-E1-01` (Contract Register), all pipeline execution stories.
*   **Risk Level**: Critical
*   **Impact if Unresolved**: Cannot trigger pipeline execution or align spark/runtime dependencies with the client's environment.
*   **Proposed Adapter/Interface**: `PipelineExecutionAdapter` with `LocalProcessAdapter` (for dev) and `DatabricksAdapter` (for prod) implementations.
*   **Information Needed to Confirm**: Workspace URL, PAT/Service Principal auth setup, default cluster/policy IDs.
*   **Current Status**: Unconfirmed

#### UNK-002: Databricks control table DDL
*   **Category**: Infrastructure
*   **What is Unknown**: Exact schema of `batch_control`, `batch_stage_status`, and any other existing platform tables.
*   **Which Stories Depend on It**: `CF-V0-E1-01` (Explicitly flagged as an assumption).
*   **Risk Level**: Critical
*   **Impact if Unresolved**: Cannot correctly write audit/batch records. Faking this risks breaking production integrations upon deployment.
*   **Proposed Adapter/Interface**: `ControlTableRepository` with `InMemoryRepository` (for dev) and `DatabricksSqlRepository` implementations.
*   **Information Needed to Confirm**: DDL export for all metadata/control tables currently in use.
*   **Current Status**: Unconfirmed

#### UNK-003: Cloud storage configuration
*   **Category**: Infrastructure
*   **What is Unknown**: Storage provider (Azure Blob? ADLS Gen2? S3?), container names, and access patterns (SAS tokens vs Managed Identity).
*   **Which Stories Depend on It**: `CF-V0-E3-01` (Minimal feed record), file processing features.
*   **Risk Level**: High
*   **Impact if Unresolved**: Unable to mount or read/write landing and Bronze layer files.
*   **Proposed Adapter/Interface**: `StorageAdapter` with `LocalFilesystemAdapter` and `AzureBlobAdapter`/`AdlsAdapter` implementations.
*   **Information Needed to Confirm**: Storage account URI, directory taxonomy, and authentication method.
*   **Current Status**: Unconfirmed

#### UNK-004: Airflow configuration
*   **Category**: Infrastructure
*   **What is Unknown**: Airflow version, DAG deployment method, connection details, variable management, and hosting (MWAA, Composer, self-hosted).
*   **Which Stories Depend on It**: `CF-V5-E1-02` (Harvester), `CF-V1-E4-03` (Publish & Schedule).
*   **Risk Level**: High
*   **Impact if Unresolved**: Cannot generate/deploy DAGs mechanically from configuration; cannot harvest old configs.
*   **Proposed Adapter/Interface**: `OrchestrationAdapter` with `MockSchedulerAdapter` and `AirflowApiAdapter` implementations.
*   **Information Needed to Confirm**: Deployment method, API endpoint/credentials for DAG syncing.
*   **Current Status**: Unconfirmed

#### UNK-005: Network topology
*   **Category**: Infrastructure
*   **What is Unknown**: VPN requirements, private endpoints, firewall rules connecting the CINQFLOW app backplane to Databricks and Storage.
*   **Which Stories Depend on It**: All environments; basic platform connectivity.
*   **Risk Level**: High
*   **Impact if Unresolved**: Platform deployment fails at network perimeter. Services won't talk to each other.
*   **Proposed Adapter/Interface**: N/A (Handled via IaC), but abstract data calls via resilient clients that can handle transient connectivity timeouts.
*   **Information Needed to Confirm**: Subnets, Private Link requirements, NSG rules.
*   **Current Status**: Unconfirmed

#### UNK-006: VDI/environment access
*   **Category**: Infrastructure
*   **What is Unknown**: Credentials, provisioning, and access routing to development environments.
*   **Which Stories Depend on It**: ALL (Flagged as Scrum Blocker).
*   **Risk Level**: Critical
*   **Impact if Unresolved**: Team cannot test in reality; forced to work entirely in a detached local simulation.
*   **Proposed Adapter/Interface**: N/A
*   **Information Needed to Confirm**: Login details and instructions from the Help Desk.
*   **Current Status**: Investigating / Blocker

#### UNK-007: Database environment access
*   **Category**: Infrastructure
*   **What is Unknown**: Credentials and connection strings to the target application database.
*   **Which Stories Depend on It**: ALL data-plane and UI backend stories (Flagged as Scrum Blocker).
*   **Risk Level**: Critical
*   **Impact if Unresolved**: No centralized persistence; team forced to use local SQLite/Postgres isolating their work.
*   **Proposed Adapter/Interface**: N/A
*   **Information Needed to Confirm**: Database connection string, firewall whitelisting.
*   **Current Status**: Investigating / Blocker

### Integration Unknowns

#### UNK-008: Verato API specification
*   **Category**: Integration
*   **What is Unknown**: Endpoint URLs, authentication methods, request/response schemas, SLAs, rate limits, sandbox availability.
*   **Which Stories Depend on It**: Wave 3 Identity Resolution epics.
*   **Risk Level**: High
*   **Impact if Unresolved**: Identity resolution features cannot be integrated; deterministic reconciliation with the MPI is impossible.
*   **Proposed Adapter/Interface**: `IdentityResolutionAdapter` with `MockIdentityAdapter` (dev) and `VeratoAdapter` (prod) implementations.
*   **Information Needed to Confirm**: Verato API documentation and Sandbox credentials.
*   **Current Status**: Unconfirmed

#### UNK-009: Enterprise notification infrastructure
*   **Category**: Integration
*   **What is Unknown**: Transport methods for alerts (SMTP/Email, Teams/Slack webhooks, PagerDuty, SNS).
*   **Which Stories Depend on It**: `CF-V4-E2-04` (Emergency access notification), Alerting flows.
*   **Risk Level**: Medium
*   **Impact if Unresolved**: Platform cannot proactively alert operators or security teams to incidents.
*   **Proposed Adapter/Interface**: `NotificationAdapter` with `ConsoleNotificationAdapter` and `EmailAdapter`/`TeamsWebhookAdapter` implementations.
*   **Information Needed to Confirm**: SMTP server or Webhook URLs.
*   **Current Status**: Unconfirmed

#### UNK-010: Microsoft Entra ID configuration
*   **Category**: Integration
*   **What is Unknown**: Tenant ID, App Registration details, client secrets, security group mappings for MVP roles.
*   **Which Stories Depend on It**: `CF-V0-E2-01` (Sign-in), `CF-V4-E2-02` (Role matrix).
*   **Risk Level**: Critical
*   **Impact if Unresolved**: Security is broken by default; no user authentication or RBAC can function.
*   **Proposed Adapter/Interface**: `AuthenticationAdapter` with `LocalMockAuthAdapter` and `EntraIdAdapter`.
*   **Information Needed to Confirm**: OIDC discovery document URL, Client ID/Secret, defined Group Object IDs.
*   **Current Status**: Unconfirmed

#### UNK-011: LLM provider
*   **Category**: Integration
*   **What is Unknown**: Cloud provider (Azure OpenAI? Vertex?), model versions, rate limits, API keys, and whether PHI is technically allowed in prompts.
*   **Which Stories Depend on It**: `CF-V1-E5-02` (AI Schema), `CF-V1-E6-02` (AI Mapping).
*   **Risk Level**: High
*   **Impact if Unresolved**: Cannot develop or prompt-engineer AI features without knowing the target model's capabilities/context limits.
*   **Proposed Adapter/Interface**: `LlmInferenceAdapter` with `MockLlmAdapter` and `AzureOpenAiAdapter`.
*   **Information Needed to Confirm**: Azure OpenAI Endpoint, Deployment Name, API keys.
*   **Current Status**: Unconfirmed

#### UNK-012: Legacy SQL Server database
*   **Category**: Integration
*   **What is Unknown**: Connection details for the read-only identity comparison lookups needed during the coexistence period.
*   **Which Stories Depend on It**: `CF-V3-E9-04` (Legacy coexistence).
*   **Risk Level**: Medium
*   **Impact if Unresolved**: Cannot maintain backward compatibility and parallel-run during Wave 5 migration.
*   **Proposed Adapter/Interface**: `LegacyDatabaseAdapter` with `MockSqlAdapter` and `SqlServerAdapter`.
*   **Information Needed to Confirm**: Connection strings, view schemas, read-only credentials.
*   **Current Status**: Unconfirmed

#### UNK-013: SFTP/file transfer infrastructure
*   **Category**: Integration
*   **What is Unknown**: The exact mechanism by which files arrive in the landing zone (SFTP? Managed File Transfer agent?).
*   **Which Stories Depend on It**: `CF-V1-E3-02` (Full Feed Registry).
*   **Risk Level**: Medium
*   **Impact if Unresolved**: Do not know how to trigger ingestion mechanically.
*   **Proposed Adapter/Interface**: `FileTransferAdapter` with `LocalTransferAdapter` and `SftpAdapter`.
*   **Information Needed to Confirm**: Hostname, ports, protocols, drop-off paths.
*   **Current Status**: Unconfirmed

### Data Unknowns

#### UNK-014: Existing feed inventory
*   **Category**: Data
*   **What is Unknown**: The full, exhaustive list of the 41+ production feeds and their current physical configs.
*   **Which Stories Depend on It**: `CF-V5-E1-03` (Feed Inventory), `CF-V5-E1-04`.
*   **Risk Level**: High
*   **Impact if Unresolved**: Risk of missing critical feeds during wave planning, leading to cutover delays.
*   **Proposed Adapter/Interface**: `InventorySourceAdapter`
*   **Information Needed to Confirm**: An authoritative spreadsheet or database export of current live feeds.
*   **Current Status**: Unconfirmed

#### UNK-015: Canonical model workbooks
*   **Category**: Data
*   **What is Unknown**: The actual approved Member, Enrollment, Claims, Provider, and Encounter model definitions.
*   **Which Stories Depend on It**: `CF-V1-E6-01` (Canonical Browser), `CF-V1-E6-03`.
*   **Risk Level**: High
*   **Impact if Unresolved**: Cannot build the mapping studio or test schema targets; mapping has no destination.
*   **Proposed Adapter/Interface**: `CanonicalModelRepository` with `LocalModelRepo` and `DatabaseModelRepo`.
*   **Information Needed to Confirm**: The finalized logical data model documentation/DDL.
*   **Current Status**: Unconfirmed

#### UNK-016: Business glossary source
*   **Category**: Data
*   **What is Unknown**: The exact format and location of the 171 business terms, including their confirmed PHI flags.
*   **Which Stories Depend on It**: `CF-V1-E5-03` (PHI Detection), `CF-V1-E6-01`.
*   **Risk Level**: Medium
*   **Impact if Unresolved**: AI detection lacks authoritative definitions to map to; PHI flags may be inaccurate.
*   **Proposed Adapter/Interface**: `GlossaryAdapter` with `CsvGlossaryAdapter` and `EnterpriseGlossaryAdapter`.
*   **Information Needed to Confirm**: Export of the current glossary/data dictionary.
*   **Current Status**: Unconfirmed

#### UNK-017: Incumbent GitHub repository structure
*   **Category**: Data
*   **What is Unknown**: Flow files, mapping workbooks, and DAGs layout in the legacy repositories.
*   **Which Stories Depend on It**: `CF-V5-E1-02` (Harvester).
*   **Risk Level**: Medium
*   **Impact if Unresolved**: The AI Harvester cannot extract configuration automatically; requires manual data entry.
*   **Proposed Adapter/Interface**: `RepositoryScannerAdapter` with `LocalDirectoryScanner` and `GitHubApiScanner`.
*   **Information Needed to Confirm**: GitHub URLs, repository access tokens.
*   **Current Status**: Unconfirmed

#### UNK-018: Reference data / lookup tables
*   **Category**: Data
*   **What is Unknown**: Source and format for code translation tables, holiday calendars, etc.
*   **Which Stories Depend on It**: `CF-V1-E6-03` (Manual Mapping Editor), rules engine.
*   **Risk Level**: Medium
*   **Impact if Unresolved**: Data enrichment and lookup transformations will fail in runtime.
*   **Proposed Adapter/Interface**: `ReferenceDataAdapter` with `InMemoryReferenceAdapter` and `DbReferenceAdapter`.
*   **Information Needed to Confirm**: Table names, DB locations, update frequency.
*   **Current Status**: Unconfirmed

#### UNK-019: Sample files for each feed type
*   **Category**: Data
*   **What is Unknown**: Actual sample files that represent the real incoming data shapes.
*   **Which Stories Depend on It**: `CF-V1-E4-01` (Wizard), `CF-V1-E5-01` (Profiler).
*   **Risk Level**: High
*   **Impact if Unresolved**: Development of profiler and AI schema inference is completely ungrounded.
*   **Proposed Adapter/Interface**: `SampleDataRepository`
*   **Information Needed to Confirm**: 5-10 de-identified or synthetic sample files provided by the client.
*   **Current Status**: Unconfirmed

### Security Unknowns

#### UNK-020: PHI handling policy
*   **Category**: Security
*   **What is Unknown**: The exact definition of PHI beyond HIPAA minimums that the client enforces.
*   **Which Stories Depend on It**: `CF-V4-E2-03` (PHI Masking).
*   **Risk Level**: High
*   **Impact if Unresolved**: Potential privacy violations or excessive masking that hinders operations.
*   **Proposed Adapter/Interface**: `PhiMaskingAdapter` with `DefaultMasker` and `ClientPolicyMasker`.
*   **Information Needed to Confirm**: Client's formal Data Classification Policy.
*   **Current Status**: Unconfirmed

#### UNK-021: Data residency requirements
*   **Category**: Security
*   **What is Unknown**: Specific geo-restrictions on where data can be stored, cached, or processed.
*   **Which Stories Depend on It**: All infrastructure deployment epics.
*   **Risk Level**: Critical
*   **Impact if Unresolved**: Deploying in the wrong region could violate legal agreements, forcing a tear-down.
*   **Proposed Adapter/Interface**: N/A (Deployment configuration).
*   **Information Needed to Confirm**: Allowed cloud regions (e.g., East US vs Azure Government).
*   **Current Status**: Unconfirmed

#### UNK-022: AI data processing policy
*   **Category**: Security
*   **What is Unknown**: Can explicitly scrubbed PHI go to cloud AI? What model/tenant restrictions exist?
*   **Which Stories Depend on It**: `CF-V1-E5-02`, `CF-V1-E6-02` (All AI flows).
*   **Risk Level**: High
*   **Impact if Unresolved**: InfoSec could outright block the AI features that form the core value proposition of Wave 1.
*   **Proposed Adapter/Interface**: `AIPrivacyGateway` with `PassThroughGateway` and `ScrubbingGateway`.
*   **Information Needed to Confirm**: Explicit written sign-off from Client InfoSec.
*   **Current Status**: Unconfirmed

#### UNK-023: Audit retention policy
*   **Category**: Security
*   **What is Unknown**: How long must audit logs be kept in hot/cold storage to meet compliance?
*   **Which Stories Depend on It**: `CF-V4-E2-04` (Audit Trail).
*   **Risk Level**: Medium
*   **Impact if Unresolved**: Storage cost overruns or compliance failure during a state audit.
*   **Proposed Adapter/Interface**: `AuditLogAdapter` with `DbAuditAdapter` (hot) and `ColdStorageAuditAdapter` (archival).
*   **Information Needed to Confirm**: Legal retention duration rules.
*   **Current Status**: Unconfirmed

#### UNK-024: Break-glass / emergency access policy
*   **Category**: Security
*   **What is Unknown**: Are there existing ITSM tools (e.g., ServiceNow) that MUST integrate with our break-glass process?
*   **Which Stories Depend on It**: `CF-V4-E2-04` (Emergency Access).
*   **Risk Level**: Medium
*   **Impact if Unresolved**: The custom break-glass workflow may violate enterprise IT policies.
*   **Proposed Adapter/Interface**: `EmergencyAccessAdapter` with `InternalApprovalAdapter` and `ItsmIntegrationAdapter`.
*   **Information Needed to Confirm**: Client incident management runbooks.
*   **Current Status**: Unconfirmed

### Process Unknowns

#### UNK-025: Approval routing rules
*   **Category**: Process
*   **What is Unknown**: Which specific roles approve which object types? Is there a formal RACI?
*   **Which Stories Depend on It**: `CF-V1-E4-03` (Submit/Approve).
*   **Risk Level**: High
*   **Impact if Unresolved**: Governance workflows cannot be correctly configured, halting object state transitions.
*   **Proposed Adapter/Interface**: `ApprovalRoutingAdapter` with `DefaultRoutingAdapter` and `ClientRaciAdapter`.
*   **Information Needed to Confirm**: Signed-off RACI matrix for configuration changes.
*   **Current Status**: Unconfirmed

#### UNK-026: SLA definitions per feed
*   **Category**: Process
*   **What is Unknown**: Actual expected arrival windows and processing deadlines for priority feeds.
*   **Which Stories Depend on It**: `CF-V1-E3-02` (SLA alerting).
*   **Risk Level**: Medium
*   **Impact if Unresolved**: Operations dashboard cannot correctly render RAG (Red/Amber/Green) statuses.
*   **Proposed Adapter/Interface**: `SlaEvaluationAdapter`
*   **Information Needed to Confirm**: Feed schedules and business service-level agreements.
*   **Current Status**: Unconfirmed

#### UNK-027: Release window schedule
*   **Category**: Process
*   **What is Unknown**: When are approved changes physically permitted to activate in production?
*   **Which Stories Depend on It**: `CF-V1-E6-04` (Mapping versioning).
*   **Risk Level**: Medium
*   **Impact if Unresolved**: We might build immediate promotion when the client requires batched weekend releases.
*   **Proposed Adapter/Interface**: `DeploymentWindowAdapter` with `ImmediateDeploymentAdapter` and `ScheduledWindowAdapter`.
*   **Information Needed to Confirm**: IT change management schedule.
*   **Current Status**: Unconfirmed

#### UNK-028: Escalation chains
*   **Category**: Process
*   **What is Unknown**: Who gets paged for what severity (L1/L2/L3)?
*   **Which Stories Depend on It**: Alerting/Ops epics.
*   **Risk Level**: Medium
*   **Impact if Unresolved**: Critical pipeline failures go unnoticed.
*   **Proposed Adapter/Interface**: `EscalationAdapter`
*   **Information Needed to Confirm**: On-call rosters and severity matrices.
*   **Current Status**: Unconfirmed

### Deployment Unknowns

#### UNK-029: Target deployment platform
*   **Category**: Deployment
*   **What is Unknown**: Is the final target Azure AKS, Azure App Service, on-prem Docker, or AWS ECS?
*   **Which Stories Depend on It**: Deployment (specifically Kranthi's local Docker task).
*   **Risk Level**: Critical
*   **Impact if Unresolved**: Container architecture built in dev might fail or require refactoring to run in prod.
*   **Proposed Adapter/Interface**: N/A (Infrastructure configuration pattern).
*   **Information Needed to Confirm**: Target compute architecture topology.
*   **Current Status**: Unconfirmed

#### UNK-030: CI/CD pipeline
*   **Category**: Deployment
*   **What is Unknown**: The required orchestration tool (Azure DevOps, GitHub Actions, Jenkins).
*   **Which Stories Depend on It**: Delivery pipelines.
*   **Risk Level**: Medium
*   **Impact if Unresolved**: Hand-offs to operations will be manual and error-prone.
*   **Proposed Adapter/Interface**: N/A
*   **Information Needed to Confirm**: CI/CD platform standard.
*   **Current Status**: Unconfirmed

#### UNK-031: Container registry
*   **Category**: Deployment
*   **What is Unknown**: Target registry for finalized docker images (ACR, ECR, internal Artifactory).
*   **Which Stories Depend on It**: Build pipelines.
*   **Risk Level**: Low
*   **Impact if Unresolved**: Cannot push artifacts, but can build locally.
*   **Proposed Adapter/Interface**: N/A
*   **Information Needed to Confirm**: Registry URI and push credentials.
*   **Current Status**: Unconfirmed

#### UNK-032: SSL/TLS certificate management
*   **Category**: Deployment
*   **What is Unknown**: Certificate Authority, cert provisioning, and auto-renewal mechanisms.
*   **Which Stories Depend on It**: Secure endpoints setup.
*   **Risk Level**: Medium
*   **Impact if Unresolved**: UI and API endpoints will throw security warnings or fail client infosec review.
*   **Proposed Adapter/Interface**: N/A
*   **Information Needed to Confirm**: Internal CA vs Public CA process.
*   **Current Status**: Unconfirmed

#### UNK-033: DNS and domain configuration
*   **Category**: Deployment
*   **What is Unknown**: Internal friendly domains and CNAME routing.
*   **Which Stories Depend on It**: App routing.
*   **Risk Level**: Low
*   **Impact if Unresolved**: Application is accessible only via raw IP or unmemorable URI.
*   **Proposed Adapter/Interface**: N/A
*   **Information Needed to Confirm**: Target domain name (e.g. `cinqflow.client.internal`).
*   **Current Status**: Unconfirmed
