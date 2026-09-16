# CINQFLOW API Design Document

This document outlines the API surface for CINQFLOW, divided into two primary sections: Wave 0 (which must be implemented immediately) and Future Waves (which are documented for architectural visibility).

## General API Guidelines

### API Versioning
All endpoints are versioned in the URL path, e.g., `/api/v1/...`.

### Authentication
All API endpoints (except public health/liveness endpoints, if any) require a Bearer token in the `Authorization` header:
`Authorization: Bearer <JWT_TOKEN>`

### Standard Error Response Format
Errors follow standard HTTP status codes and return a consistent JSON payload:
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "details": ["Optional array", "of specific", "validation errors"]
  }
}
```

### Pagination Format
List endpoints that return multiple items use cursor-based or offset-based pagination:
```json
{
  "items": [ ... ],
  "pagination": {
    "total": 150,
    "offset": 0,
    "limit": 50,
    "hasNext": true
  }
}
```
Query parameters `?limit=50&offset=0` are used to control pagination.

### Rate Limiting
APIs will be rate-limited by IP and User/Service Principal, returning `429 Too Many Requests` when limits are exceeded. Specific limits will be defined per environment and tier.

---

## Section 1: Wave 0 API Surface (IMPLEMENT NOW)

Only the following endpoint groups are implemented in Wave 0.

### 1. Authentication

#### POST `/api/v1/auth/login`
- **Purpose**: Exchange an AuthProvider token for a CINQFLOW session/JWT (uses MockAuthProvider in dev, EntraAuthProvider in prod).
- **Request Body**: `{ "token": "provider_token" }`
- **Response Body**: `{ "accessToken": "jwt_token", "expiresIn": 3600 }`
- **Authorization**: Public
- **Audit**: Log successful login and failures.

#### POST `/api/v1/auth/logout`
- **Purpose**: Invalidate the current session.
- **Request Body**: None
- **Response Body**: `{ "message": "Logged out successfully" }`
- **Authorization**: Any authenticated user.
- **Audit**: Log logout event.

#### GET `/api/v1/auth/me`
- **Purpose**: Retrieve the current user profile, roles, and permissions.
- **Request Body**: None
- **Response Body**: 
  ```json
  {
    "id": "uuid",
    "email": "user@example.com",
    "roles": ["DataSteward", "Admin"],
    "permissions": ["feeds:read", "contracts:write"]
  }
  ```
- **Authorization**: Any authenticated user.

### 2. Contract Register

#### GET `/api/v1/contracts`
- **Purpose**: List contract register entries.
- **Query Params**: `limit`, `offset`, `status`
- **Request Body**: None
- **Response Body**: `{ "items": [...], "pagination": {...} }`
- **Authorization**: `contracts:read`
- **Pagination**: Yes

#### POST `/api/v1/contracts`
- **Purpose**: Create a contract register entry.
- **Request Body**: `{ "name": "...", "providerId": "...", "validFrom": "...", "validTo": "..." }`
- **Response Body**: `{ "id": "uuid", ... }`
- **Authorization**: `contracts:write`
- **Audit**: Log creation.

#### GET `/api/v1/contracts/{id}`
- **Purpose**: Get a single contract entry.
- **Request Body**: None
- **Response Body**: `{ "id": "uuid", ... }`
- **Authorization**: `contracts:read`

#### PUT `/api/v1/contracts/{id}`
- **Purpose**: Update a contract entry.
- **Request Body**: `{ "name": "...", "validTo": "..." }`
- **Response Body**: `{ "id": "uuid", ... }`
- **Authorization**: `contracts:write`
- **Audit**: Log modification with before/after state diff.

#### POST `/api/v1/contracts/{id}/unknowns`
- **Purpose**: Record an unknown entity/provider related to the contract.
- **Request Body**: `{ "unknownIdentifier": "...", "context": "..." }`
- **Response Body**: `{ "id": "unknown_uuid", "status": "Pending" }`
- **Authorization**: `contracts:write` or Pipeline Service Role.

#### PUT `/api/v1/contracts/unknowns/{id}/confirm`
- **Purpose**: Confirm an unknown (e.g., mapping to an existing entity or creating a new one).
- **Request Body**: `{ "resolutionType": "MapToExisting", "targetId": "..." }`
- **Response Body**: `{ "id": "unknown_uuid", "status": "Confirmed" }`
- **Authorization**: `contracts:write`
- **Audit**: Log confirmation decision.

#### GET `/api/v1/contracts/risk-view`
- **Purpose**: Get a rolled-up risk view of all unconfirmed unknowns.
- **Request Body**: None
- **Response Body**: `{ "totalUnconfirmed": 12, "highRisk": 5, "byContract": [...] }`
- **Authorization**: `contracts:read`

### 3. Feed Registry

#### GET `/api/v1/feeds`
- **Purpose**: List feeds, scoped by authorization.
- **Query Params**: `limit`, `offset`, `sourceSystem`
- **Request Body**: None
- **Response Body**: `{ "items": [...], "pagination": {...} }`
- **Authorization**: `feeds:read`
- **Pagination**: Yes

#### POST `/api/v1/feeds`
- **Purpose**: Create minimal feed record (6 fields).
- **Request Body**: 
  ```json
  {
    "name": "Provider Feed",
    "sourceSystem": "SystemA",
    "domain": "Provider",
    "filePattern": "*.csv",
    "schedule": "Daily",
    "ownerId": "uuid"
  }
  ```
- **Response Body**: `{ "id": "feed_uuid", "version": 1, ... }`
- **Authorization**: `feeds:write`
- **Audit**: Log feed creation.

#### GET `/api/v1/feeds/{id}`
- **Purpose**: Get feed with its active version.
- **Request Body**: None
- **Response Body**: `{ "id": "feed_uuid", "version": 1, ... }`
- **Authorization**: `feeds:read`

#### PUT `/api/v1/feeds/{id}`
- **Purpose**: Update feed (creates a new version; configuration is immutable per version).
- **Request Body**: `{ "filePattern": "*_v2.csv", ... }`
- **Response Body**: `{ "id": "feed_uuid", "version": 2, ... }`
- **Authorization**: `feeds:write`
- **Audit**: Log feed update and new version creation.

#### GET `/api/v1/feeds/{id}/versions`
- **Purpose**: Get version history of a feed.
- **Request Body**: None
- **Response Body**: `{ "items": [{"version": 1}, {"version": 2}] }`
- **Authorization**: `feeds:read`

#### POST `/api/v1/feeds/{id}/validate-pattern`
- **Purpose**: Validate a file pattern against a sample filename.
- **Request Body**: `{ "sampleName": "provider_20231010.csv" }`
- **Response Body**: `{ "matches": true, "extractedDate": "2023-10-10" }`
- **Authorization**: `feeds:read`

### 4. Input Registration

#### GET `/api/v1/inputs`
- **Purpose**: List registered inputs (files landed).
- **Query Params**: `limit`, `offset`, `status`, `feedId`
- **Response Body**: `{ "items": [...], "pagination": {...} }`
- **Authorization**: `inputs:read`
- **Pagination**: Yes

#### GET `/api/v1/inputs/{id}`
- **Purpose**: Get input file details.
- **Response Body**: `{ "id": "input_uuid", "fileName": "...", "sizeBytes": 1024, "status": "Processed" }`
- **Authorization**: `inputs:read`

#### POST `/api/v1/inputs/register`
- **Purpose**: Register a new file arrival (internal API, called by landing worker).
- **Request Body**: `{ "s3Path": "...", "fileName": "...", "sizeBytes": 1024, "checksum": "..." }`
- **Response Body**: `{ "id": "input_uuid", "status": "Registered" }`
- **Authorization**: Pipeline Service Role
- **Audit**: Log file arrival.
- **Lifecycle Restrictions**: Duplicate checksums/paths should be rejected or handled idempotently.

### 5. Pipeline Execution

#### POST `/api/v1/pipeline/execute`
- **Purpose**: Trigger a pipeline run for a feed.
- **Request Body**: `{ "feedId": "...", "inputId": "..." }`
- **Response Body**: `{ "batchId": "batch_uuid", "status": "Running" }`
- **Authorization**: `pipeline:execute`
- **Audit**: Log pipeline trigger.

#### GET `/api/v1/pipeline/batches`
- **Purpose**: List batches.
- **Query Params**: `feedId`, `status`, `startDate`, `endDate`, `limit`, `offset`
- **Response Body**: `{ "items": [...], "pagination": {...} }`
- **Authorization**: `pipeline:read`
- **Pagination**: Yes

#### GET `/api/v1/pipeline/batches/{id}`
- **Purpose**: Get batch detail with current stage status.
- **Response Body**: `{ "batchId": "...", "feedId": "...", "status": "Failed", "currentStage": "Silver" }`
- **Authorization**: `pipeline:read`

#### GET `/api/v1/pipeline/batches/{id}/stages`
- **Purpose**: Get all stage records for a batch.
- **Response Body**: `{ "items": [{"stage": "Bronze", "status": "Success"}, {"stage": "Silver", "status": "Failed"}] }`
- **Authorization**: `pipeline:read`

#### POST `/api/v1/pipeline/batches/{id}/restart`
- **Purpose**: Restart a failed batch from its last completed stage.
- **Request Body**: None
- **Response Body**: `{ "batchId": "...", "status": "Running", "restartedFrom": "Bronze" }`
- **Authorization**: `pipeline:execute`
- **Audit**: Log batch restart action.

### 6. Quarantine

#### GET `/api/v1/quarantine`
- **Purpose**: List quarantined records.
- **Query Params**: `batchId`, `feedId`, `reason`, `limit`, `offset`
- **Response Body**: `{ "items": [...], "pagination": {...} }`
- **Authorization**: `quarantine:read`
- **Pagination**: Yes

#### GET `/api/v1/quarantine/{id}`
- **Purpose**: Get detail of a specific quarantine record.
- **Response Body**: `{ "id": "...", "originalData": {...}, "reason": "SchemaMismatch", "batchId": "..." }`
- **Authorization**: `quarantine:read`

### 7. Reconciliation

#### GET `/api/v1/reconciliation/batches/{batchId}`
- **Purpose**: Get reconciliation summary for a batch.
- **Response Body**: `{ "batchId": "...", "rowsReceived": 1000, "rowsProcessed": 980, "rowsDropped": 20 }`
- **Authorization**: `reconciliation:read`

#### GET `/api/v1/reconciliation/batches/{batchId}/ledger`
- **Purpose**: Get the named-reason drop ledger for a batch.
- **Response Body**: `{ "items": [{"reason": "MissingProviderId", "count": 15}, {"reason": "InvalidDate", "count": 5}] }`
- **Authorization**: `reconciliation:read`

### 8. Audit

#### GET `/api/v1/audit/events`
- **Purpose**: Search audit events (immutable, read-only).
- **Query Params**: `actorId`, `action`, `resourceId`, `startDate`, `endDate`, `limit`, `offset`
- **Response Body**: `{ "items": [...], "pagination": {...} }`
- **Authorization**: `audit:read`
- **Pagination**: Yes

#### GET `/api/v1/audit/events/{id}`
- **Purpose**: Get a single audit event.
- **Response Body**: `{ "id": "...", "timestamp": "...", "actorId": "...", "action": "...", "details": {...} }`
- **Authorization**: `audit:read`

---

## Section 2: Future Wave APIs (DOCUMENTED ONLY — NOT IMPLEMENTED IN WAVE 0)

### Wave 1
- **Schema CRUD**: `GET/POST/PUT /api/v1/schemas`
- **Profiling**: `POST /api/v1/schemas/{id}/profile`
- **AI Schema Inference**: `POST /api/v1/schemas/infer`
- **Mapping CRUD**: `GET/POST/PUT /api/v1/mappings`
- **AI Mapping Suggestions**: `POST /api/v1/mappings/suggest`
- **Rule CRUD**: `GET/POST/PUT /api/v1/rules`
- **Rule Testing**: `POST /api/v1/rules/test`
- **Approval Workflow**: `POST /api/v1/approvals/...`
- **Glossary**: `GET/POST/PUT /api/v1/glossary`
- **Onboarding Wizard**: `POST /api/v1/onboarding/start`
- **Scheduling**: `GET/POST/PUT /api/v1/schedules`

### Wave 2
- **Operations Dashboard**: `GET /api/v1/ops/dashboard`
- **Batch Monitor**: `GET /api/v1/ops/monitor/batches`
- **Governed Actions**: `POST /api/v1/ops/actions/execute`
- **Incidents**: `GET/POST/PUT /api/v1/incidents`
- **Alerts**: `GET/POST/PUT /api/v1/alerts`
- **Variance Management**: `GET/POST/PUT /api/v1/variance`
- **Certification**: `POST /api/v1/certification/certify`

### Wave 3
- **Identity Resolution**: `GET/POST /api/v1/identity/...`
- **Crosswalk**: `GET/POST/PUT /api/v1/crosswalks`
- **Exception Queue**: `GET/POST/PUT /api/v1/exceptions`
- **Merge/Split**: `POST /api/v1/identity/merge`, `POST /api/v1/identity/split`
- **ODS Model Management**: `GET/POST/PUT /api/v1/ods/models`
- **ODS Certification**: `POST /api/v1/ods/certify`
- **Financial Reconciliation**: `GET/POST /api/v1/finance/reconciliation`

### Wave 4
- **Full Role Matrix**: `GET/POST/PUT /api/v1/roles`
- **PHI Masking**: `POST /api/v1/security/masking-rules`
- **Access Reviews**: `GET/POST/PUT /api/v1/security/access-reviews`
- **Emergency Access**: `POST /api/v1/security/emergency-access`
- **Releases**: `GET/POST/PUT /api/v1/releases`
- **Freeze Windows**: `GET/POST/PUT /api/v1/releases/freeze-windows`
- **Catalog**: `GET /api/v1/catalog`
- **Knowledge Base**: `GET/POST/PUT /api/v1/kb`
- **Copilot**: `POST /api/v1/copilot/query`

### Wave 5
- **Migration Inventory**: `GET/POST/PUT /api/v1/migration/inventory`
- **Harvester**: `POST /api/v1/migration/harvester/run`
- **Parallel-Run Comparison**: `GET/POST /api/v1/migration/compare`
- **Wave Tracking**: `GET /api/v1/migration/waves`
- **Cutover**: `POST /api/v1/migration/cutover`
- **Ownership Transfer**: `POST /api/v1/migration/transfer-ownership`
