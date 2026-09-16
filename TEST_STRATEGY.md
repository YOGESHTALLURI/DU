# CINQFLOW Test Strategy

This document outlines the comprehensive test strategy for the CINQFLOW healthcare data platform. It defines the testing methodologies, coverage targets, and specific verification strategies required to ensure the platform's reliability, security, and accuracy.

## Tech Stack Context
- **Backend:** Python 3.12+ / FastAPI / SQLAlchemy / Celery
- **Frontend:** Next.js 14+ / TypeScript / React Testing Library
- **Database:** PostgreSQL 16+
- **Testing Tools:** pytest, httpx, factory_boy, Playwright

---

## 1. Unit Testing
**Objective:** Verify individual components function correctly in isolation.
- **Backend:** Utilize `pytest` with fixtures. Mock external dependencies (e.g., AWS S3, external APIs) to ensure tests are fast and deterministic.
- **Frontend:** Utilize `Jest` combined with `React Testing Library` to test components, hooks, and utility functions.
- **Coverage Targets:** ≥ 80% line coverage strictly enforced for all business logic.
- **Scope:** 
  - Services, validators, data transforms, and rule engine logic.
  - Reconciliation logic and math.
  - PHI masking algorithms and utilities.

## 2. API Testing
**Objective:** Validate all backend endpoints for functionality, security, and contract adherence.
- **Tools:** `httpx` AsyncClient integrated with FastAPI `TestClient`.
- **Scope:**
  - **Happy Path & Validation:** Verify expected successful responses and correct handling of malformed requests.
  - **Authorization:** Test every endpoint against all 7 defined roles (Business Analyst, Data Steward, Data Engineer, Operations, Approver, Administrator, Read-Only).
  - **Lifecycle Restrictions:** Ensure operations on objects respect their state (e.g., cannot edit a 'Retired' feed).
  - **Contract Testing:** Verify request/response payloads match defined OpenAPI schemas.
  - **Rate Limiting:** Confirm endpoints gracefully reject requests exceeding defined limits.

## 3. Database Testing
**Objective:** Ensure schema integrity, migration reliability, and query performance.
- **Migrations:** Automated testing of Alembic migrations (applying `upgrade` and then `downgrade`) to verify schema changes don't cause data loss.
- **Constraints & Triggers:** Verify database constraints (foreign keys, uniqueness) and audit triggers correctly log every state change.
- **Performance:** Benchmark common and complex queries to ensure they meet SLA requirements.
- **Integrity:** Test data integrity constraints and complex cascading deletes/updates.

## 4. Pipeline Testing
**Objective:** Validate the metadata-driven data ingestion and processing pipelines.
- **Metadata-Driven Execution:** Tests must define feeds purely via metadata/configuration without hardcoded pipeline logic. No feed-specific code branching (e.g., no `if feed == "FIDELIS"`).
- **Wave 0 Stage Verification:** Independently verify Landing → Bronze → Silver Raw transitions. Identity and Silver ODS stages are introduced in Wave 3 and tested separately.
- **Restart/Recovery:** Ensure pipelines can restart from the last completed stage without data duplication or loss.
- **Idempotent Input Processing:** Repeated submission of the same input fingerprint must not create duplicate processing or duplicate results. Verified via input fingerprint/hash, unique database constraints, input registry, batch state, stage state, and transaction boundaries.
- **Quarantine Routing:** Deliberately inject bad records and verify they are routed to quarantine with explicit, named reasons, preserving the original record.
- **Bronze Immutability:** Verify that the Bronze layer strictly preserves the original source file unchanged.
- **Wave 0 Demo Feed:** Use the deterministic sample CSV (member_id, first_name, last_name, date_of_birth, gender) with valid and intentionally invalid records to prove: Input rows = Silver Raw rows + Quarantined rows (e.g., 4 in = 3 Silver Raw + 1 Quarantine).
- **Real Execution:** Wave 0 tests must execute the actual pipeline (discover metadata, detect file, register input, fingerprint, validate, create batch, execute Landing/Bronze/Silver Raw, quarantine, reconcile, audit). No fake pipeline success responses.

## 5. Integration Testing
**Objective:** Verify that different internal and external services work together correctly.
- **End-to-End Flow:** Programmatically trigger and monitor the flow: File arrival → Landing → Bronze → Silver Raw.
- **Cross-Service:** Verify API interactions with background workers (Celery) and subsequent database updates.
- **Adapters:** Use robust mock implementations (adapter/interface boundaries) for external systems; never assume external production systems are available or create fake implementations pretending they are.

## 6. End-to-End (E2E) Testing
**Objective:** Validate critical user journeys from the user's perspective in a real browser.
- **Tools:** Playwright.
- **Critical Journeys:**
  - Login → navigate → perform standard action → verify result.
  - Complete "Onboarding Wizard" flow (Upload → Schema → Map → Rules → Publish).
  - Complete "Approval Workflow" (Submit → Review → Approve/Reject).
  - "Operations Triage" flow (View batch → Identify failure → Retry/Acknowledge).
- **Visual Regression:** Capture and compare screenshots of critical UI components to detect unintended visual changes.

## 7. Security Testing
**Objective:** Prevent unauthorized access, data breaches, and common web vulnerabilities.
- **Authentication:** Test valid, invalid, expired, and revoked Entra ID tokens.
- **Authorization Matrix:** Test every role against every endpoint to ensure strict RBAC compliance.
- **Scope Enforcement:** Verify "User A cannot see User B's scoped data" (e.g., NY vs GA feeds).
- **Vulnerability:** Automated testing for CSRF, XSS, and SQL Injection prevention.
- **Rate Limiting:** Validate API rate limiting across endpoints to prevent abuse.

## 8. Authorization Testing
**Objective:** Deep dive into role-based access control and segregation of duties.
- **Dedicated Suite:** For each of the 7 roles, explicit tests verifying:
  - Accessible resources and endpoints.
  - Inaccessible resources and endpoints (must return 403, not 404).
  - Scope filtering works correctly at the data query level.
  - Read-only enforcement is applied at the API/Data layer, not merely by hiding UI buttons.
  - **Segregation of Duties:** Explicitly verify that an author cannot approve their own change. Required approvals must be enforced server-side.

## 9. AI Evaluation Testing
**Objective:** Ensure AI components are accurate, safe, and explicitly act as proposals.
- **Schema Inference:** ≥ 90% accuracy (accepted without human correction).
- **Mapping Suggestions:** ≥ 85% agreement with existing human workbooks.
- **Rule Generation:** ≥ 90% intent-equivalent accuracy on a curated golden dataset.
- **PHI Detection:** 100% recall on glossary-flagged PHI fields.
- **Failure Fingerprinting:** ≥ 95% precision in identifying root causes.
- **Copilot Citations:** 100% of factual claims made by the Copilot must include citations.
- **Confidence Calibration:** Verify that reported confidence scores align with actual accuracy.
- **Safety:**
  - Strict resistance to prompt injection attacks.
  - **Zero Tolerance:** Absolute verification that no unmasked PHI is ever leaked into AI prompts.
  - AI outputs must *always* remain as "Draft" proposals until explicitly approved by a human.
  - AI must never invent unsupported values.

## 10. PHI Leakage Testing
**Objective:** Guarantee that Protected Health Information is never exposed inappropriately.
- **Masking Verification:** Verify masking logic in UI rendering, error messages, system logs, quarantine views, data exports, and AI prompts.
- **Log Scanning:** Automated background scanning of test log output for patterns resembling PHI (SSNs, DOBs, Names).
- **Exports:** Verify exports are watermarked with the user and timestamp.
- **Audit Trails:** Verify that intentional "unmask" actions are explicitly recorded in the audit trail.

## 11. Idempotency Testing
**Objective:** Ensure repeated operations yield the same state.
- **File Processing:** Processing the same file multiple times results in zero duplicate records.
- **Batch Restart:** Resuming a failed batch does not re-process already completed stages.
- **API Calls:** Repeated POST/PUT requests with the same idempotency key yield the exact same result.
- **Scheduling:** Overlapping cron triggers result in only a single pipeline execution.

## 12. Restart/Recovery Testing
**Objective:** Ensure system resilience in the face of infrastructure or processing failures.
- **Failure Simulation:** Intentionally crash the pipeline at each distinct stage (Landing, Bronze, Silver, etc.).
- **Recovery:** Verify the system successfully restarts from the last completed stage.
- **Data Integrity:** Verify no data is corrupted, duplicated, or dropped upon restart.
- **State Management:** Ensure the batch status correctly reflects the restart event and is captured in the audit trail.

## 13. Reconciliation Testing
**Objective:** Mathematically prove no records are silently lost or created.
- **Row Accounting:** Explicitly assert `rows_in = rows_out + quarantined + dropped` at every pipeline stage.
- **Drop Ledger:** Ensure the ledger of dropped records contains explicit, named reasons (no 'other' or 'unknown' buckets allowed).
- **Financial & Member:** Financial reconciliation accuracy (adjustment chain netting) and Member universe set-wise comparison.
- **Variances:** Verify variance detection logic and threshold breach alerts.

## 14. Migration Parallel-Run Testing
**Objective:** Validate that the new platform produces output identical to or explicitly better than the incumbent system.
- **Value Comparison:** Perform strict value-level comparisons (not just aggregate row counts).
- **Difference Register:** Maintain a register of *approved* differences where CINQFLOW is intentionally fixing legacy bugs.
- **Trend Tracking:** Track comparison metrics over an extended parallel-run window.
- **Gates:** Verify entry and exit criteria gates for migration phases.

---

## Testing Infrastructure
- **Databases:** Separate, isolated PostgreSQL instance per test run to ensure clean state.
- **Fixtures:** Extensive use of `factory_boy` for generating relational data models.
- **Test Data:** Curated, seeded sample files covering each supported feed type.
- **CI/CD:** Full test suite execution required on every Pull Request before merge.
- **Local Dev:** Provide `docker-compose` setup for complete local test environment execution.
- **Reporting:** Generate comprehensive coverage reports and maintain a test results dashboard.

## Test Data Management
- **Synthetic Data:** Absolutely NO real PHI in any test environments. All data must be synthetic.
- **Golden Datasets:** Maintain static, golden datasets exclusively for evaluating AI prompt accuracy and deterministic logic.
- **Formats:** Maintain sample files for every supported format: CSV, Excel, fixed-width, NDJSON, and FHIR.
- **Failure Seeds:** Maintain specific, seeded failure scenarios to validate the failure fingerprint testing.

---

## Test Matrix: User Stories to Test Types

| Epic / Story ID | Feature Description | Primary Test Types | Critical Verification |
| :--- | :--- | :--- | :--- |
| **Epic 1** | **Migration** | | |
| CF-V0-E1-01 | Execution-Plane Contract Register | Unit, API, E2E | Metadata immutability |
| CF-V5-E1-02 | AI Config Harvester | Unit, AI Eval | No AI auto-approval |
| **Epic 2** | **Security & Roles** | | |
| CF-V0-E2-01 | SSO & Basic Roles | API, E2E, Authz | Audit trail written |
| CF-V4-E2-02 | Full Role Matrix & Scope | API, Authz | Read-only enforcement at API |
| CF-V4-E2-03 | PHI Masking Everywhere | Unit, PHI Leakage, E2E | Masked in logs/errors |
| CF-V4-E2-04 | Audit Trail & Emergency | API, DB, E2E | No silent state changes |
| **Epic 3** | **Feed Registry** | | |
| CF-V0-E3-01 | Minimal Feed Record | Unit, API, DB | Versioned configuration |
| CF-V1-E3-04 | Feed Lifecycle & Versioning | API, E2E | State transition validation |
| **Epic 4** | **Onboarding** | | |
| CF-V1-E4-01 | Onboarding Wizard | E2E, API | No approval by author |
| CF-V1-E4-02 | End-to-End Sample Test | Pipeline, Recon | `rows_in = rows_out + dropped` |
| **Epic 5** | **Profiling & Schema** | | |
| CF-V1-E5-01 | Deterministic File Profiler | Unit, Pipeline | Idempotent profiling |
| CF-V1-E5-02 | AI Schema Inference | AI Eval, Unit | No unsupported types |
| CF-V1-E5-03 | PHI / Code-Set Detection | AI Eval, PHI Leakage | 100% PHI recall |
| **Epic 6** | **Mapping** | | |
| CF-V1-E6-02 | AI Mapping Suggestions | AI Eval, API | Draft status until approved |
| CF-V1-E6-04 | Mapping Approval | Authz, DB, E2E | Author cannot approve |
