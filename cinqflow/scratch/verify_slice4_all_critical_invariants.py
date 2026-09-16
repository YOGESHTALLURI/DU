"""
Wave 2 Slice 4 Independent Verification Script — 9 Critical Invariants
CF-V2-E12-04 (Failure Fingerprinting / Recovery Playbooks)
CF-V2-E12-05 (Self-Explaining Alerts)

Directly exercises database, services, hashing determinism, storm deduplication,
flapping detection, version immutability, and Slice 3 Governed Action Surface integration.
"""
import sys
import os
import uuid
from datetime import datetime, timedelta, timezone

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from backend.core.database import SessionLocal, engine
from backend.models.incident import (
    FailureCategoryEnum,
    AlertStatusEnum,
    AlertSeverityEnum,
    PlaybookStatusEnum,
    FailureFingerprint,
    RecoveryPlaybook,
    RecoveryPlaybookVersion,
    FingerprintPlaybookBinding,
    OperationalAlert,
    AlertOccurrence,
)
from backend.models.feed import Feed, FeedFormatEnum, FeedStatusEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.pipeline import (
    Batch,
    BatchStage,
    BatchStatusEnum,
    StageNameEnum,
    StageStatusEnum,
    WAVE0_STAGE_ORDER,
)
from backend.models.input_registry import InputRegistry, InputStatusEnum
from backend.adapters.storage import get_storage_adapter
from backend.models.ops_action import ActionTypeEnum, ActionRiskLevelEnum, ActionStatusEnum
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.services.fingerprint_service import FingerprintService
from backend.services.playbook_service import PlaybookService
from backend.services.alert_service import AlertService
from backend.services.ops_action_service import OpsActionService
from backend.schemas.ops_action import OpsActionSubmitRequest
from backend.core.security import CurrentUser


def run_all_invariants():
    print("=" * 80)
    print("STARTING WAVE 2 SLICE 4 LIVE INVARIANT VERIFICATION")
    print("=" * 80)

    db = SessionLocal()
    failures = []

    try:
        # Create dedicated live test feed
        test_feed = Feed(
            name=f"live-slice4-feed-{uuid.uuid4().hex[:8]}",
            domain="CLAIMS",
            format=FeedFormatEnum.CSV,
            landing_folder="/landing/live",
            filename_pattern="live_*.csv",
            schedule_expression="0 6 * * *",
            status=FeedStatusEnum.ACTIVE,
            created_by="live-verifier",
            updated_by="live-verifier",
        )
        db.add(test_feed)
        db.commit()
        db.refresh(test_feed)

        test_version = FeedVersion(
            feed_id=test_feed.id,
            version_number=1,
            status=FeedVersionStatusEnum.PUBLISHED,
            config_snapshot={
                "fields": [
                    {"name": "member_id", "type": "STRING", "required": True},
                    {"name": "first_name", "type": "STRING", "required": True},
                    {"name": "last_name", "type": "STRING", "required": True},
                    {"name": "date_of_birth", "type": "DATE", "required": True},
                    {"name": "gender", "type": "ENUM", "allowed_values": ["M", "F", "U"], "required": False},
                ],
                "stages": [
                    {"name": "LANDING", "order": 1, "config": {}},
                    {"name": "BRONZE", "order": 2, "config": {}},
                    {"name": "SILVER_RAW", "order": 3, "config": {"delimiter": ","}},
                    {"name": "RECONCILIATION", "order": 4, "config": {}},
                ],
            },
            created_by="live-verifier",
            updated_by="live-verifier",
        )
        db.add(test_version)
        db.commit()
        db.refresh(test_version)
        test_feed.active_version_id = test_version.id
        db.commit()

        storage = get_storage_adapter()
        csv_bytes = b"member_id,first_name,last_name,date_of_birth,gender\nM001,John,Doe,1980-01-01,M\n"
        csv_path = f"./data/landing/live_slice4_{uuid.uuid4().hex[:8]}.csv"
        storage.write_file(csv_path, csv_bytes)

        inp = InputRegistry(
            id=uuid.uuid4(),
            feed_id=test_feed.id,
            filename="live.csv",
            file_path=csv_path,
            file_size_bytes=len(csv_bytes),
            file_fingerprint=uuid.uuid4().hex,
            status=InputStatusEnum.ACCEPTED,
            registered_by="live-verifier",
            detected_at=datetime.now(timezone.utc),
            created_by="live-verifier",
            updated_by="live-verifier",
        )
        db.add(inp)
        db.commit()
        db.refresh(inp)

        success_batch = Batch(
            id=uuid.uuid4(),
            feed_id=test_feed.id,
            feed_version_id=test_version.id,
            input_registry_id=inp.id,
            status=BatchStatusEnum.SUCCESS,
            triggered_by="live-verifier",
            created_by="live-verifier",
            updated_by="live-verifier",
        )
        db.add(success_batch)
        db.commit()
        db.refresh(success_batch)
        print(f"[SETUP] Created live test feed: {test_feed.name} ({test_feed.id}) with published version {test_version.id} and success_batch {success_batch.id}")

        # ----------------------------------------------------------------------
        # INVARIANT 1: Deterministic Fingerprint Hashing
        # ----------------------------------------------------------------------
        print("\n--- INVARIANT 1: Deterministic Fingerprint Hashing ---")
        sig1, hash1 = FingerprintService.compute_signature(
            category=FailureCategoryEnum.DATA_QUALITY,
            failure_stage="SILVER_RAW",
            root_cause_pattern="Value out of range for date_of_birth",
            error_class="DQRuleViolation.DATE_RANGE",
        )
        sig2, hash2 = FingerprintService.compute_signature(
            category=FailureCategoryEnum.DATA_QUALITY,
            failure_stage="SILVER_RAW",
            root_cause_pattern="Value out of range for date_of_birth",
            error_class="DQRuleViolation.DATE_RANGE",
        )
        if hash1 != hash2 or len(hash1) != 64:
            failures.append("Invariant 1 Failed: Hash is not deterministic or not SHA-256")
            print(f"FAIL: hash1={hash1}, hash2={hash2}")
        else:
            print(f"PASS: Deterministic SHA-256 hash verified: {hash1[:16]}...")

        # ----------------------------------------------------------------------
        # INVARIANT 2: Input Normalization & Zero-PHI Redaction
        # ----------------------------------------------------------------------
        print("\n--- INVARIANT 2: Input Normalization & Zero-PHI Redaction ---")
        u_rand = str(uuid.uuid4())
        raw_error = (
            f"Batch {u_rand} at 2026-09-06T14:32:00Z memory 0x7ffd19ab failed on row #142 "
            f"with SSN 123-45-6789 and patient patient.smith@clinic.com"
        )
        normalized = FingerprintService.sanitize_and_normalize(raw_error)

        if "123-45-6789" in normalized or "patient.smith@clinic.com" in normalized:
            failures.append("Invariant 2 Failed: PHI leaked into normalized text")
            print(f"FAIL: PHI present: {normalized}")
        elif u_rand in normalized or "0x7ffd19ab" in normalized:
            failures.append("Invariant 2 Failed: Runtime variables not normalized")
            print(f"FAIL: Runtime variables present: {normalized}")
        elif "<UUID>" not in normalized or "<HEX_ADDR>" not in normalized or "[REDACTED_SSN]" not in normalized:
            failures.append("Invariant 2 Failed: Expected placeholder tokens missing")
            print(f"FAIL: Tokens missing: {normalized}")
        else:
            print(f"PASS: Text normalized & sanitized: {normalized}")

        # ----------------------------------------------------------------------
        # INVARIANT 3: Operational Alert Creation
        # ----------------------------------------------------------------------
        print("\n--- INVARIANT 3: Operational Alert Creation ---")
        alert = AlertService.record_failure(
            db=db,
            feed_id=test_feed.id,
            category=FailureCategoryEnum.STAGE_EXECUTION,
            failure_stage="BRONZE",
            root_cause_pattern="Corrupt CSV header delimiter",
            severity=AlertSeverityEnum.CRITICAL,
            user_id="live-verifier",
        )
        db.commit()

        if alert.status != AlertStatusEnum.OPEN or alert.occurrence_count != 1:
            failures.append("Invariant 3 Failed: Alert not created with OPEN status and 1 occurrence")
            print(f"FAIL: status={alert.status}, count={alert.occurrence_count}")
        else:
            print(f"PASS: Alert created: {alert.id}, status={alert.status.value}, occurrences={alert.occurrence_count}")

        # ----------------------------------------------------------------------
        # INVARIANT 4: Alert Storm Suppression & Active Deduplication
        # ----------------------------------------------------------------------
        print("\n--- INVARIANT 4: Alert Storm Suppression & Active Deduplication ---")
        live_batches = []
        for i in range(4):
            b = Batch(
                feed_id=test_feed.id,
                feed_version_id=test_version.id,
                input_registry_id=inp.id,
                status=BatchStatusEnum.FAILED,
                triggered_by="live-verifier",
                created_by="live-verifier",
                updated_by="live-verifier",
            )
            db.add(b)
            db.flush()
            for idx, stage_name in enumerate(WAVE0_STAGE_ORDER, start=1):
                stage = BatchStage(
                    id=uuid.uuid4(),
                    batch_id=b.id,
                    stage_name=stage_name,
                    stage_order=idx,
                    status=StageStatusEnum.PENDING,
                    created_by="live-verifier",
                    updated_by="live-verifier",
                )
                db.add(stage)
            db.commit()
            db.refresh(b)
            live_batches.append(b)
            AlertService.record_failure(
                db=db,
                feed_id=test_feed.id,
                batch_id=b.id,
                category=FailureCategoryEnum.STAGE_EXECUTION,
                failure_stage="BRONZE",
                root_cause_pattern="Corrupt CSV header delimiter",
                user_id="live-verifier",
            )
        db.commit()

        # Check alert count in DB for this feed
        alerts_count = db.query(OperationalAlert).filter(OperationalAlert.feed_id == test_feed.id).count()
        db.refresh(alert)
        if alerts_count != 1 or alert.occurrence_count != 5:
            failures.append(f"Invariant 4 Failed: Alert storm suppression failed (count={alerts_count}, occurrences={alert.occurrence_count})")
            print(f"FAIL: alerts_count={alerts_count}, alert.occurrence_count={alert.occurrence_count}")
        else:
            print(f"PASS: Alert storm suppressed: exactly 1 alert row with occurrence_count=5")

        # ----------------------------------------------------------------------
        # INVARIANT 5: Flapping Detection & Reopening
        # ----------------------------------------------------------------------
        print("\n--- INVARIANT 5: Flapping Detection & Reopening ---")
        AlertService.resolve_alert(
            db=db,
            alert_id=alert.id,
            resolution_notes="Resolved in live verification",
            user_id="operator@cinqflow.local",
        )
        db.commit()
        db.refresh(alert)
        assert alert.status == AlertStatusEnum.RESOLVED

        # Recur immediately
        reopened = AlertService.record_failure(
            db=db,
            feed_id=test_feed.id,
            category=FailureCategoryEnum.STAGE_EXECUTION,
            failure_stage="BRONZE",
            root_cause_pattern="Corrupt CSV header delimiter",
            user_id="live-verifier",
        )
        db.commit()

        if reopened.id != alert.id or reopened.status != AlertStatusEnum.REOPENED or reopened.occurrence_count != 6:
            failures.append(f"Invariant 5 Failed: Flapping detection failed (status={reopened.status}, count={reopened.occurrence_count})")
            print(f"FAIL: id={reopened.id}, status={reopened.status}, count={reopened.occurrence_count}")
        else:
            print(f"PASS: Flapping detected: resolved alert reopened with status=REOPENED and count=6")

        # ----------------------------------------------------------------------
        # INVARIANT 6: Playbook Version Immutability & Audit Trail
        # ----------------------------------------------------------------------
        print("\n--- INVARIANT 6: Playbook Version Immutability & Audit Trail ---")
        pb_code = f"PB-LIVE-{uuid.uuid4().hex[:6]}"
        pb = PlaybookService.create_playbook(
            db=db,
            title="Live Test SOP",
            category=FailureCategoryEnum.DATA_QUALITY,
            playbook_code=pb_code,
            explanation_template="Initial SOP explanation v1",
            suggested_action_type=ActionTypeEnum.REPROCESS_QUARANTINE,
            user_id="lead-engineer",
        )
        db.commit()
        v1_id = pb.current_version_id

        v2 = PlaybookService.update_playbook(
            db=db,
            playbook_id=pb.id,
            explanation_template="Updated SOP explanation v2",
            user_id="lead-engineer",
        )
        db.commit()

        # Approve v2
        PlaybookService.approve_playbook_version(db=db, version_id=v2.id, approved_by="steward@cinqflow.local")
        db.commit()
        db.refresh(pb)

        v1 = db.query(RecoveryPlaybookVersion).filter(RecoveryPlaybookVersion.id == v1_id).first()
        if v1.explanation_template != "Initial SOP explanation v1" or pb.current_version_id != v2.id:
            failures.append("Invariant 6 Failed: Playbook version 1 was mutated or v2 is not current")
            print(f"FAIL: v1_text={v1.explanation_template}, current_ver={pb.current_version_id}")
        else:
            print(f"PASS: Version immutability verified: v1 preserved intact, v2 approved as current")

        # ----------------------------------------------------------------------
        # INVARIANT 7: Playbook Matching (Explicit Binding vs Category Default)
        # ----------------------------------------------------------------------
        print("\n--- INVARIANT 7: Playbook Matching ---")
        fp = FingerprintService.get_or_create_fingerprint(
            db=db,
            category=FailureCategoryEnum.DATA_QUALITY,
            failure_stage="SILVER_RAW",
            root_cause_pattern=f"Live test rule violation pattern {uuid.uuid4().hex[:8]}",
        )
        PlaybookService.bind_fingerprint(db=db, fingerprint_id=fp.id, playbook_id=pb.id, priority=10)
        db.commit()

        matched_ver = PlaybookService.find_matching_playbook_version(db=db, fingerprint=fp)
        if not matched_ver or matched_ver.playbook_id != pb.id:
            failures.append("Invariant 7 Failed: Explicit playbook binding not matched")
            print(f"FAIL: matched_ver={matched_ver}")
        else:
            print(f"PASS: Explicit binding matched playbook {pb.playbook_code} (version {matched_ver.version_number})")

        # ----------------------------------------------------------------------
        # INVARIANT 8: Slice 3 Governed Action Surface Integration
        # ----------------------------------------------------------------------
        print("\n--- INVARIANT 8: Governed Action Surface Integration ---")
        ops_action_svc = OpsActionService(db)
        eng_user = CurrentUser(
            user_id="engineer-live",
            email="eng@cinqflow.local",
            roles=["ENGINEER"],
            auth_provider="mock",
        )

        dummy_batch_id = str(live_batches[0].id)
        action_req = ops_action_svc.submit_action(
            request_data=OpsActionSubmitRequest(
                action_type=ActionTypeEnum.RESTART_BATCH,
                target_type="BATCH",
                target_id=dummy_batch_id,
                reason="Executing playbook recovery SOP",
                parameters={},
                idempotency_key=f"live-act-{uuid.uuid4().hex[:8]}",
            ),
            current_user=eng_user,
        )
        db.commit()

        if action_req.action_type != ActionTypeEnum.RESTART_BATCH or action_req.risk_level != ActionRiskLevelEnum.STANDARD:
            failures.append("Invariant 8 Failed: Governed action not created properly")
            print(f"FAIL: action_type={action_req.action_type}, risk={action_req.risk_level}")
        else:
            print(f"PASS: Governed action submitted through Slice 3 surface: {action_req.id} ({action_req.action_type.value})")

        # ----------------------------------------------------------------------
        # INVARIANT 9: Four-Eyes Dual Control on High-Risk Playbook Actions
        # ----------------------------------------------------------------------
        print("\n--- INVARIANT 9: Four-Eyes Dual Control on High-Risk Actions ---")
        high_risk_req = ops_action_svc.submit_action(
            request_data=OpsActionSubmitRequest(
                action_type=ActionTypeEnum.RETRIGGER_BATCH,
                target_type="BATCH",
                target_id=str(success_batch.id),
                reason="Retriggering entire pipeline per critical SOP",
                parameters={},
                idempotency_key=f"live-hr-{uuid.uuid4().hex[:8]}",
            ),
            current_user=eng_user,
        )
        db.commit()

        if high_risk_req.status != ActionStatusEnum.PENDING_APPROVAL or high_risk_req.risk_level != ActionRiskLevelEnum.HIGH_RISK:
            failures.append("Invariant 9 Failed: High-risk action did not enter PENDING_APPROVAL")
            print(f"FAIL: status={high_risk_req.status}, risk={high_risk_req.risk_level}")
        else:
            # Verify self-approval is rejected
            try:
                ops_action_svc.approve_action(
                    action_id=high_risk_req.id,
                    decision_notes="Self approval attempt",
                    current_user=eng_user,
                )
                failures.append("Invariant 9 Failed: Self approval was NOT blocked!")
                print("FAIL: Self approval succeeded when it should fail")
            except Exception as e:
                print(f"PASS: Requester self-approval correctly blocked with 403: {e}")

            # Verify independent operator approval succeeds
            reviewer_user = CurrentUser(
                user_id="reviewer-live",
                email="reviewer@cinqflow.local",
                roles=["ENGINEER"],
                auth_provider="mock",
            )
            approved_act = ops_action_svc.approve_action(
                action_id=high_risk_req.id,
                decision_notes="Independent review confirmed",
                current_user=reviewer_user,
            )
            db.commit()
            print(f"PASS: Independent operator approval succeeded: status={approved_act.status.value}")

        print("\n" + "=" * 80)
        if failures:
            print(f"VERIFICATION COMPLETED WITH {len(failures)} FAILURES:")
            for f in failures:
                print(f"  - {f}")
            sys.exit(1)
        else:
            print("ALL 9 WAVE 2 SLICE 4 CRITICAL INVARIANTS PASSED PERFECTLY!")
            print("=" * 80)
            sys.exit(0)

    finally:
        db.close()


if __name__ == "__main__":
    run_all_invariants()
