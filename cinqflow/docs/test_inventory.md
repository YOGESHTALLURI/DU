# CINQFLOW Test Inventory & Suite Reconciliation

## 1. Executive Summary

- **Total Test Modules**: 72
- **Total Test Cases Collected & Passing**: **547**
- **Test Results**: **547 passed, 0 failed, 0 errors, 0 skipped, 0 xfailed**
- **Test Pass Rate**: **100.0%**
- **Execution Target**: Live PostgreSQL 16 Alpine (`cinqflow_postgres`), `localhost:5432`

---

## 2. Test Baseline & Progression Reconciliation

### 2.1 Baseline Progression
- **Wave 3 Slice 3 Accepted Baseline**: **456 tests** across 68 test modules.
- **Wave 3 Slice 4 Execution Infrastructure**: **28 tests** across 2 modules (`test_lease_utils.py`, `test_ods_lease_fencing.py`).
- **Wave 3 Business Scope (CF-V3-E9-03 & CF-V3-E8-05)**: **37 tests** across 2 modules (`test_merge_split_service.py` [23 tests], `test_pipeline_identity_stage.py` [14 tests]).
- **Wave 3 Slice 5 Scope (CF-V3-E10-03 ODS Certification & Consumer Gate)**: **26 tests** across 2 modules (`test_ods_certification.py` [20 tests], `test_ods_certification_views.py` [6 tests]).
- **Total Verified Suite**: 456 + 28 + 37 + 26 = **547 tests**.

---

## 3. Wave 3 Business Stories Test Inventory (37 Tests)

### 3.1 Unit Tests: `tests/unit/test_merge_split_service.py` (23 Tests - CF-V3-E9-03)

| # | Test Function Name | Identifier | Purpose |
|---|---|---|---|
| 1 | `test_ms_prop_1_create_merge_proposal_success` | MS-PROP-1 | Propose merge of two active master identities, enters `PENDING_APPROVAL`. |
| 2 | `test_ms_prop_2_duplicate_client_key_rejected` | MS-PROP-2 | Idempotent proposal submission with duplicate `client_key` returns existing proposal. |
| 3 | `test_ms_prop_3_proposer_cannot_approve_own_proposal` | MS-PROP-3 | Four-Eyes segregation: proposer attempting self-approval raises HTTP 403. |
| 4 | `test_ms_prop_4_approver_can_approve_valid_proposal` | MS-PROP-4 | Legitimate second steward approves proposal, transitions state to `APPROVED`. |
| 5 | `test_ms_prop_5_cannot_approve_non_pending_proposal` | MS-PROP-5 | State machine guard: approving an already approved/rejected proposal raises HTTP 409. |
| 6 | `test_ms_prop_6_cannot_execute_unapproved_proposal` | MS-PROP-6 | Execution guard: executing an unapproved proposal raises HTTP 409. |
| 7 | `test_ms_exec_1_merge_transitions_master_status_merged` | MS-EXEC-1 | Merge execution: transitions source status to `MERGED` and sets `merged_into_cinq_id`. |
| 8 | `test_ms_exec_2_merge_repoints_crosswalk_to_target` | MS-EXEC-2 | Merge execution: closes source crosswalk with `valid_to=now()` and creates new target crosswalk (`MERGE_OVERRIDE`). |
| 9 | `test_ms_exec_3_merge_deactivates_source_tokens` | MS-EXEC-3 | Merge execution: deactivates source identity tokens (`is_current=False`, `effective_to=now()`). |
| 10 | `test_ms_exec_4_merge_appends_event_ledger` | MS-EXEC-4 | Append-only event ledger: records immutable `IdentityMergeSplitEvent` with `event_type=MERGE`. |
| 11 | `test_ms_exec_5_split_allocates_new_cinq_id` | MS-EXEC-5 | Split execution: allocates new active `MasterIdentity` when splitting an erroneously linked identifier. |
| 12 | `test_ms_exec_6_split_retires_previous_crosswalk_interval` | MS-EXEC-6 | Split execution: terminates previous crosswalk validity interval and creates new active link (`SPLIT_OVERRIDE`). Inherits token anchor. |
| 13 | `test_ms_exec_6b_split_multi_crosswalk_moves_only_requested_identifier` | MS-EXEC-6B | Split precision: when source identity has multiple active crosswalks, moves ONLY the requested `(source_system, source_identifier_hash)`. |
| 14 | `test_ms_exec_6c_split_rejects_missing_or_mismatched_crosswalk` | MS-EXEC-6C | Split validation: rejects split proposal targeting a non-existent or inactive crosswalk with HTTP 404. |
| 15 | `test_ms_exec_7_point_in_time_reconstruction_before_merge` | MS-EXEC-7 | Historical reconstruction: query `as_of` timestamp prior to merge resolves correctly to source identity. |
| 16 | `test_ms_exec_8_point_in_time_reconstruction_after_merge` | MS-EXEC-8 | Post-merge reconstruction: query `as_of` timestamp after merge resolves to target surviving identity. |
| 17 | `test_ms_zero_phi_proposal_notes_enforced` | MS-ZERO-PHI | Control plane protection: submitting raw demographic patterns in proposal reason raises HTTP 422. |
| 18 | `test_ms_concurrency_lock_prevents_race` | MS-LOCK-RACE | Concurrency protection: execution acquires PostgreSQL advisory transaction lock on identity keys. |
| 19 | `test_ms_exec_9_target_conflicting_token_rejected` | MS-EXEC-9 | Token conflict protection: splitting into target identity with conflicting active token anchor raises HTTP 409. |
| 20 | `test_ms_exec_10_split_after_merge_and_historical_reconstruction` | MS-EXEC-10 | Full lifecycle: proves merge followed by split with multi-era point-in-time reconstruction. |
| 21 | `test_ms_exec_11a_duplicate_active_crosswalk_constraint_rejected` | MS-EXEC-11A | Database uniqueness guard: proves PostgreSQL `excl_crosswalk_temporal_overlap` / `uq_active_crosswalk_source` blocks duplicate active crosswalk coordinates. |
| 22 | `test_ms_exec_11b_defensive_ambiguity_returns_conflict` | MS-EXEC-11B | Defensive ambiguity guard: service resolves exact crosswalk and raises HTTP 409 CONFLICT if multiple active matches are found. |
| 23 | `test_ms_exec_12_repeat_split_proposal_execution_idempotent` | MS-EXEC-12 | Idempotency guard: executing an already EXECUTED split proposal returns existing event and creates zero duplicate rows. |

### 3.2 Integration Tests: `tests/integration/test_pipeline_identity_stage.py` (14 Tests - CF-V3-E8-05)

| # | Test Function Name | Identifier | Purpose |
|---|---|---|---|
| 24 | `test_pipe_id_1_stage_registration_in_wave3_order` | PIPE-ID-1 | Verifies pipeline compiler emits `WAVE3_STAGE_ORDER` including `IDENTITY` and `ODS`. |
| 25 | `test_pipe_id_2_execution_generates_identity_run_status` | PIPE-ID-2 | Verifies batch execution persists `IdentityRunStatus` row with `run_status=SUCCESS` and `completed_at`. |
| 26 | `test_pipe_id_3_high_confidence_records_auto_linked` | PIPE-ID-3 | Verifies records meeting deterministic score threshold (>85.00) are auto-linked to active crosswalks. |
| 27 | `test_pipe_id_4_ambiguous_records_routed_to_exceptions` | PIPE-ID-4 | Verifies ambiguous match candidates are routed to `identity_exceptions` with status `PENDING`. |
| 28 | `test_pipe_id_5_no_viable_candidate_routed_to_exceptions` | PIPE-ID-5 | Verifies unmatched records with no viable candidate enter exception queue with status `PENDING`. |
| 29 | `test_pipe_id_6_idempotent_restart_skips_completed_identity_stage` | PIPE-ID-6 | Idempotent restart: restarting batch when `IDENTITY` stage is `SUCCESS` leaves `completed_at` unchanged. |
| 30 | `test_pipe_id_7_identity_failure_blocks_downstream_ods` | PIPE-ID-7 | Durable gating: simulated failure at identity stage halts pipeline and blocks ODS stage execution. |
| 31 | `test_pipe_id_8_identity_success_unblocks_downstream_ods` | PIPE-ID-8 | Durable gating: identity stage completion unblocks and allows downstream ODS stage execution. |
| 32 | `test_pipe_id_9_checkpoint_lease_protects_identity_stage` | PIPE-ID-9 | Checkpoint tracking: identity stage executes within ordered batch stage lifecycle. |
| 33 | `test_pipe_id_10_concurrent_batch_executions_isolated` | PIPE-ID-10 | Isolation: concurrent batches running identity stage generate distinct `identity_run_id` records. |
| 34 | `test_pipe_id_11_zero_phi_in_batch_identity_telemetry` | PIPE-ID-11 | Zero-PHI verification: stage execution telemetry and audit logs contain 0 raw demographic data. |
| 35 | `test_pipe_id_12_full_pipeline_e2e_landing_to_identity` | PIPE-ID-12 | End-to-end: executes full pipeline LANDING -> BRONZE -> SILVER_RAW -> IDENTITY -> ODS with 100% success. |
| 36 | `test_pipe_id_13_durable_silver_raw_read_and_restart_resilience` | PIPE-ID-13 | Durable input: identity stage reads from batch-bound Silver Raw CSV file; survives in-memory context clearing. |
| 37 | `test_pipe_id_14_ods_historical_immutability_and_lineage_preservation` | PIPE-ID-14 | ODS integrity: canonical ODS member records are append-only batch-bound rows preserved across crosswalk mutations. |

---

## 4. Wave 3 Execution Infrastructure Tests (28 Tests)

### 4.1 Unit Tests: `tests/unit/test_lease_utils.py` (16 Tests)
- `test_lease1_claim_creates_bound_row` (LEASE-1)
- `test_lease2_transition_to_in_progress_succeeds` (LEASE-2)
- `test_lease3_transition_fails_wrong_token` (LEASE-3)
- `test_lease4_heartbeat_extends_expiry` (LEASE-4)
- `test_lease5_heartbeat_fails_wrong_token` (LEASE-5)
- `test_lease6_heartbeat_fails_when_expired` (LEASE-6)
- `test_lease7_validate_passes_for_valid_owner` (LEASE-7)
- `test_lease8_validate_raises_on_wrong_token` (LEASE-8)
- `test_lease9_validate_raises_on_expired_lease` (LEASE-9)
- `test_lease10_finish_success_clears_lease` (LEASE-10)
- `test_lease11_finish_failure_clears_lease` (LEASE-11)
- `test_lease12_finish_success_blocked_when_expired` (LEASE-12)
- `test_lease13_reclaim_produces_new_token` (LEASE-13)
- `test_finish_exp_1_expired_owner_cannot_finish_success` (FINISH-EXP-1)
- `test_finish_exp_2_expired_owner_cannot_finish_failure` (FINISH-EXP-2)
- `test_finish_exp_4_non_expired_owner_can_finish` (FINISH-EXP-VALID)

### 4.2 Integration Tests: `tests/integration/test_ods_lease_fencing.py` (12 Tests)
- `test_lease14_stale_worker_real_ods_mutation_blocked` (LEASE-14)
- `test_finish_exp_3_success_blocked_after_expiry` (FINISH-EXP-3)
- `test_finish_exp_4_failure_blocked_after_expiry` (FINISH-EXP-4)
- `test_savepoint_1_operation_hash_duplicate_outer_transaction_survives` (SAVEPOINT-1)
- `test_savepoint_2_unrelated_integrity_error_propagates` (SAVEPOINT-2)
- `test_conc_1_two_reclaimers_only_one_wins` (CONC-1)
- `test_conc_2_heartbeat_fails_after_reclaim` (CONC-2)
- `test_conc_3_finish_blocked_after_reclaim` (CONC-3)
- `test_conc_4_validate_raises_after_reclaim` (CONC-4)
- `test_multiple_executions_coexist_for_same_batch` (DB-INV-1)
- `test_identity_run_status_check_constraint` (DB-INV-2)
- `test_identity_run_status_composite_pk_rejects_duplicate` (DB-INV-3)

---

## 5. Pre-Existing Baseline Test Modules (456 Tests Across 68 Files)

| Module | Test Count | Module | Test Count |
|---|---|---|---|
| `test_approval_security.py` | 4 | `test_approval_service.py` | 8 |
| `test_authorization.py` | 8 | `test_canonical_models.py` | 4 |
| `test_certification_service.py` | 4 | `test_complex_profiler.py` | 4 |
| `test_contracts.py` | 7 | `test_database_constraints.py` | 7 |
| `test_downstream_protection.py` | 14 | `test_drift_and_dq_api.py` | 5 |
| `test_e2e_wave1_slice3_workflow.py` | 1 | `test_feeds.py` | 5 |
| `test_feeds_v1.py` | 5 | `test_glossary.py` | 16 |
| `test_glossary_security.py` | 6 | `test_glossary_workflow.py` | 5 |
| `test_governance_zero_phi_comprehensive.py` | 2 | `test_governed_activation_workflow.py` | 6 |
| `test_health.py` | 5 | `test_identity_anchor_completeness.py` | 1 |
| `test_identity_api_and_steward.py` | 17 | `test_identity_invariants_and_zero_phi.py` | 15 |
| `test_identity_service.py` | 18 | `test_landing_controls.py` | 5 |
| `test_mapping_lifecycle.py` | 6 | `test_mapping_onboarding_governance.py` | 3 |
| `test_mapping_studio.py` | 10 | `test_ods_models.py` | 14 |
| `test_onboarding_wizard.py` | 2 | `test_ops_alert_lifecycle_and_concurrency.py` | 3 |
| `test_ops_alert_service.py` | 10 | `test_ops_alerts_and_playbooks_api.py` | 8 |
| `test_ops_arrival_engine.py` | 10 | `test_ops_authoritative_failure_sources.py` | 4 |
| `test_ops_batch_data_certification_flow.py` | 1 | `test_ops_complete_alert_recovery_lifecycle.py` | 3 |
| `test_ops_failure_recovery_e2e.py` | 4 | `test_ops_fingerprint_service.py` | 8 |
| `test_ops_governed_action_engine.py` | 12 | `test_ops_kpi_service.py` | 8 |
| `test_ops_monitor_api.py` | 10 | `test_ops_playbook_action_targets.py` | 6 |
| `test_ops_playbook_service.py` | 6 | `test_ops_quarantine_reprocess_flow.py` | 6 |
| `test_ops_quarantine_target_contract.py` | 5 | `test_ops_recovery_api.py` | 8 |
| `test_ops_recovery_service.py` | 11 | `test_ops_variance_waiver_lifecycle.py` | 1 |
| `test_ops_zero_phi_playbook_storage.py` | 2 | `test_pipeline_e2e.py` | 3 |
| `test_production_dq_pipeline.py` | 9 | `test_production_rules.py` | 8 |
| `test_profiler.py` | 6 | `test_rule_execution.py` | 7 |
| `test_rule_governance.py` | 4 | `test_rule_lifecycle.py` | 3 |
| `test_rules.py` | 15 | `test_sandbox_executor.py` | 8 |
| `test_scheduling.py` | 12 | `test_scheduling_and_dag_workflow.py` | 4 |
| `test_scheduling_security.py` | 3 | `test_schema_drift.py` | 8 |
| `test_schemas.py` | 7 | `test_structural_transforms.py` | 9 |
| `test_variance_waiver_service.py` | 4 | `test_waiver_scopes_and_lifecycle.py` | 8 |
| `test_wave3_slice1_complex_formats_and_transforms.py` | 3 | `test_wave3_slice2_ods_core.py` | 2 |

**Subtotal Baseline**: 456 tests  
**Slice 4 Execution Infrastructure**: 28 tests  
**Wave 3 Business Scope (CF-V3-E9-03 & CF-V3-E8-05)**: 37 tests  
**Wave 3 Slice 5 (CF-V3-E10-03 ODS Certification & Consumer Compatibility Gate)**: 26 tests  
- `tests/unit/test_ods_certification.py` (20 tests):
  - `test_evaluate_batch_eligibility_success`
  - `test_evaluate_batch_eligibility_incomplete_batch`
  - `test_evaluate_batch_eligibility_failed_identity`
  - `test_evaluate_batch_eligibility_unpublished_model`
  - `test_certify_batch_success`
  - `test_certify_batch_rejection`
  - `test_certify_batch_four_eyes_violation`
  - `test_certify_batch_api_endpoint_rbac`
  - `test_certify_batch_phi_notes_rejected`
  - `test_certification_immutability_app_level`
  - `test_consumer_gate_certified_vs_uncertified`
  - `test_certification_model_creation`
  - `test_evaluate_batch_eligibility_dq_failure`
  - `test_invalid_certification_transition_db_trigger`
  - `test_ods_certification_direct_sql_delete_rejected`
  - `test_ods_certification_orm_delete_rejected`
  - `test_ods_certification_certified_record_field_mutations_rejected`
  - `test_ods_certification_failed_record_field_mutations_rejected`
  - `test_ods_certification_pending_immutable_coordinates_rejected`
  - `test_ods_certification_parent_batch_delete_rejected`
- `tests/integration/test_ods_certification_views.py` (6 tests):
  - `test_certified_views_hide_uncertified_data`
  - `test_certified_views_expose_certified_data`
  - `test_certified_views_hide_failed_certification`
  - `test_consumer_role_security_boundary`
  - `test_unauthorized_role_cannot_query_certified_views`
  - `test_e2e_pipeline_to_certification_to_consumer`

**Total Verified Test Suite**: **547 tests** (547 passed, 0 failed, 0 errors, 0 skipped, 0 xfailed).


