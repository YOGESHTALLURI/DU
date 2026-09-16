"""
Integration tests proving the complete authoritative Alert Recovery Lifecycle (Final Check 1).
Verifies:
OPEN -> ACKNOWLEDGED -> RECOVERY_IN_PROGRESS -> actual governed action execution ->
actual successful terminal outcome -> RESOLVED.
Proves that failed recovery actions do NOT resolve the alert, and validates complete audit trail
plus idempotent/retry recovery behavior.
"""
import uuid
import hashlib
import pytest
from datetime import datetime, timezone
from fastapi import HTTPException

from backend.models.incident import (
    OperationalAlert,
    FailureFingerprint,
    FailureCategoryEnum,
    AlertStatusEnum,
    AlertSeverityEnum,
)
from backend.models.ops_action import ActionTypeEnum, ActionStatusEnum, OperationalActionRequest
from backend.models.feed import Feed, FeedFormatEnum, FeedStatusEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.input_registry import InputRegistry, InputStatusEnum
from backend.models.pipeline import (
    Batch,
    BatchStage,
    BatchStatusEnum,
    StageNameEnum,
    StageStatusEnum,
    WAVE0_STAGE_ORDER,
)
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.adapters.storage import get_storage_adapter
from backend.services.alert_service import AlertService
from backend.services.playbook_service import PlaybookService
from backend.services.ops_action_service import OpsActionService
from backend.schemas.ops_action import OpsActionSubmitRequest


@pytest.fixture
def lifecycle_test_environment(db):
    """Sets up a real feed, version, and input file for pipeline execution."""
    feed = Feed(
        name=f"lifecycle-feed-{uuid.uuid4().hex[:8]}",
        domain="MEMBERS",
        format=FeedFormatEnum.CSV,
        landing_folder="/landing/lifecycle",
        filename_pattern="members_*.csv",
        schedule_expression="0 12 * * *",
        status=FeedStatusEnum.ACTIVE,
        created_by="test-setup",
        updated_by="test-setup",
    )
    db.add(feed)
    db.flush()

    ver = FeedVersion(
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        config_snapshot={
            "stages": [
                {"name": "LANDING", "order": 1, "config": {}},
                {"name": "BRONZE", "order": 2, "config": {}},
                {"name": "SILVER_RAW", "order": 3, "config": {"delimiter": ","}},
                {"name": "RECONCILIATION", "order": 4, "config": {}},
            ],
        },
        created_by="test-setup",
        updated_by="test-setup",
    )
    db.add(ver)
    db.flush()
    feed.active_version_id = ver.id
    db.flush()

    # Valid CSV content for successful restart
    storage = get_storage_adapter()
    valid_bytes = b"member_id,first_name,last_name,date_of_birth,gender\nM001,John,Doe,1980-01-01,M\n"
    file_path = f"./data/landing/lifecycle_{uuid.uuid4().hex[:8]}.csv"
    storage.write_file(file_path, valid_bytes)

    inp = InputRegistry(
        id=uuid.uuid4(),
        feed_id=feed.id,
        filename="members_valid.csv",
        file_path=file_path,
        file_size_bytes=len(valid_bytes),
        file_fingerprint=hashlib.sha256(valid_bytes).hexdigest(),
        status=InputStatusEnum.ACCEPTED,
        registered_by="test-setup",
        detected_at=datetime.now(timezone.utc),
        created_by="test-setup",
        updated_by="test-setup",
    )
    db.add(inp)
    db.flush()

    # Create approved recovery playbook recommending RESTART_BATCH
    pb = PlaybookService.create_playbook(
        db=db,
        title="Batch Restart Playbook",
        category=FailureCategoryEnum.STAGE_EXECUTION,
        playbook_code=f"PB-RESTART-{uuid.uuid4().hex[:6]}",
        explanation_template="Automated restart of failed batch",
        suggested_action_type=ActionTypeEnum.RESTART_BATCH,
    )
    PlaybookService.approve_playbook_version(db=db, version_id=pb.current_version_id, approved_by="lead")
    db.commit()

    return {
        "feed": feed,
        "version": ver,
        "input": inp,
        "playbook": pb,
        "valid_file_path": file_path,
        "valid_bytes": valid_bytes,
    }


def test_complete_alert_recovery_lifecycle_success_path(client, db, engineer_headers, lifecycle_test_environment):
    """
    Final Check 1 Steps 1-8:
    Proves OPEN -> ACKNOWLEDGED -> RECOVERY_IN_PROGRESS -> actual governed action execution ->
    actual successful terminal outcome -> RESOLVED with full audit trail.
    """
    env = lifecycle_test_environment
    feed = env["feed"]
    ver = env["version"]
    inp = env["input"]

    # Step 1: Create real failure producing an OPEN operational alert
    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=ver.id,
        input_registry_id=inp.id,
        status=BatchStatusEnum.FAILED,
        triggered_by="test-runner",
        created_by="test-runner",
        updated_by="test-runner",
    )
    db.add(batch)
    db.flush()

    for idx, stage_name in enumerate(WAVE0_STAGE_ORDER, start=1):
        stage = BatchStage(
            id=uuid.uuid4(),
            batch_id=batch.id,
            stage_name=stage_name,
            stage_order=idx,
            status=StageStatusEnum.PENDING,
            created_by="test-runner",
            updated_by="test-runner",
        )
        db.add(stage)
    db.commit()

    alert = AlertService.record_failure(
        db=db,
        feed_id=feed.id,
        batch_id=batch.id,
        category=FailureCategoryEnum.STAGE_EXECUTION,
        failure_stage="BRONZE",
        root_cause_pattern="Database connection timeout during bronze write",
        severity=AlertSeverityEnum.CRITICAL,
    )
    db.commit()

    assert alert.status == AlertStatusEnum.OPEN
    assert alert.acknowledged_at is None
    assert alert.resolved_at is None

    # Step 2: Acknowledge the alert
    ack_res = client.post(f"/api/v1/ops/alerts/{alert.id}/acknowledge", headers=engineer_headers)
    assert ack_res.status_code == 200
    alert_detail = client.get(f"/api/v1/ops/alerts/{alert.id}", headers=engineer_headers).json()
    assert alert_detail["status"] == "ACKNOWLEDGED"

    # Step 3: Start recovery
    start_rec_res = client.post(f"/api/v1/ops/alerts/{alert.id}/start-recovery", headers=engineer_headers)
    assert start_rec_res.status_code == 200
    alert_detail = client.get(f"/api/v1/ops/alerts/{alert.id}", headers=engineer_headers).json()
    assert alert_detail["status"] == "RECOVERY_IN_PROGRESS"

    # Step 4: Execute recommended governed action through Slice 3 governed action surface
    proposal = client.get(f"/api/v1/ops/alerts/{alert.id}/action-proposal", headers=engineer_headers).json()
    assert proposal["is_executable"] is True
    assert proposal["action_type"] == "RESTART_BATCH"
    assert proposal["target_type"] == "BATCH"
    assert proposal["target_id"] == str(batch.id)

    exec_res = client.post(f"/api/v1/ops/alerts/{alert.id}/execute-playbook", headers=engineer_headers)
    assert exec_res.status_code == 200
    exec_data = exec_res.json()
    assert exec_data["status"] == "COMPLETED"

    # Step 5 & 6: Verify actual underlying operation executes and reaches successful terminal state
    db.refresh(batch)
    assert batch.restart_count == 1
    assert batch.status == BatchStatusEnum.SUCCESS

    # Step 7: ONLY AFTER that successful outcome, verify the alert becomes RESOLVED
    db.refresh(alert)
    assert alert.status == AlertStatusEnum.RESOLVED
    assert alert.resolved_at is not None
    assert "Resolved automatically by successful recovery action" in alert.resolution_notes

    # Step 8: Verify complete audit trail exists for every transition
    audit_events = (
        db.query(AuditEvent)
        .filter(
            (AuditEvent.object_id == str(alert.id)) |
            (AuditEvent.object_id == str(batch.id)) |
            (AuditEvent.object_id == str(exec_data["action_id"]))
        )
        .order_by(AuditEvent.created_at.asc())
        .all()
    )
    actions_logged = [e.action.value for e in audit_events]
    assert "ops.alert_created" in actions_logged
    assert "ops.alert_acknowledged" in actions_logged
    assert "batch.restart_requested" in actions_logged
    assert "ops.action_executed" in actions_logged
    assert "batch.completed" in actions_logged
    assert "ops.alert_resolved" in actions_logged


def test_failed_governed_action_does_not_resolve_alert(client, db, engineer_headers, lifecycle_test_environment):
    """
    Final Check 1 Step 9:
    Force the governed action to fail and prove the alert does NOT become RESOLVED.
    """
    env = lifecycle_test_environment
    feed = env["feed"]
    ver = env["version"]

    # Create input pointing to a non-existent file so pipeline execution will fail
    storage = get_storage_adapter()
    ghost_path = f"./data/landing/non_existent_{uuid.uuid4().hex[:8]}.csv"

    inp = InputRegistry(
        id=uuid.uuid4(),
        feed_id=feed.id,
        filename="missing.csv",
        file_path=ghost_path,
        file_size_bytes=100,
        file_fingerprint=uuid.uuid4().hex,
        status=InputStatusEnum.ACCEPTED,
        registered_by="test-setup",
        detected_at=datetime.now(timezone.utc),
        created_by="test-setup",
        updated_by="test-setup",
    )
    db.add(inp)
    db.flush()

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=ver.id,
        input_registry_id=inp.id,
        status=BatchStatusEnum.FAILED,
        triggered_by="test-runner",
        created_by="test-runner",
        updated_by="test-runner",
    )
    db.add(batch)
    db.flush()

    for idx, stage_name in enumerate(WAVE0_STAGE_ORDER, start=1):
        stage = BatchStage(
            id=uuid.uuid4(),
            batch_id=batch.id,
            stage_name=stage_name,
            stage_order=idx,
            status=StageStatusEnum.PENDING,
            created_by="test-runner",
            updated_by="test-runner",
        )
        db.add(stage)
    db.commit()

    alert = AlertService.record_failure(
        db=db,
        feed_id=feed.id,
        batch_id=batch.id,
        category=FailureCategoryEnum.STAGE_EXECUTION,
        failure_stage="BRONZE",
        root_cause_pattern="Corrupted staging payload",
        severity=AlertSeverityEnum.CRITICAL,
    )
    db.commit()

    # Move alert to RECOVERY_IN_PROGRESS
    AlertService.start_recovery(db=db, alert_id=alert.id, user_id="engineer")
    db.commit()
    db.refresh(alert)
    assert alert.status == AlertStatusEnum.RECOVERY_IN_PROGRESS

    # Execute recovery action that will fail underlying execution
    exec_res = client.post(f"/api/v1/ops/alerts/{alert.id}/execute-playbook", headers=engineer_headers)
    assert exec_res.status_code == 400
    assert "Recovery action execution failed" in exec_res.json()["detail"]

    # PROVE: Alert does NOT become RESOLVED; strictly stays in RECOVERY_IN_PROGRESS
    db.refresh(alert)
    assert alert.status == AlertStatusEnum.RECOVERY_IN_PROGRESS
    assert alert.resolved_at is None

    # PROVE: No ops.alert_resolved audit event exists
    resolved_audit = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.object_id == str(alert.id),
            AuditEvent.action == AuditActionEnum.OPS_ALERT_RESOLVED,
        )
        .first()
    )
    assert resolved_audit is None

    # PROVE: Operational action request is recorded as FAILED
    action_req = (
        db.query(OperationalActionRequest)
        .filter(OperationalActionRequest.target_id == str(batch.id))
        .order_by(OperationalActionRequest.created_at.desc())
        .first()
    )
    assert action_req is not None
    assert action_req.status == ActionStatusEnum.FAILED


def test_deterministic_recovery_retry_and_idempotency(client, db, engineer_headers, lifecycle_test_environment):
    """
    Final Check 1 Step 10:
    Verifies deterministic recovery behavior on retry and idempotent replay.
    """
    env = lifecycle_test_environment
    feed = env["feed"]
    ver = env["version"]
    inp = env["input"]

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=ver.id,
        input_registry_id=inp.id,
        status=BatchStatusEnum.FAILED,
        triggered_by="test-runner",
        created_by="test-runner",
        updated_by="test-runner",
    )
    db.add(batch)
    db.flush()

    for idx, stage_name in enumerate(WAVE0_STAGE_ORDER, start=1):
        stage = BatchStage(
            id=uuid.uuid4(),
            batch_id=batch.id,
            stage_name=stage_name,
            stage_order=idx,
            status=StageStatusEnum.PENDING,
            created_by="test-runner",
            updated_by="test-runner",
        )
        db.add(stage)
    db.commit()

    alert = AlertService.record_failure(
        db=db,
        feed_id=feed.id,
        batch_id=batch.id,
        category=FailureCategoryEnum.STAGE_EXECUTION,
        failure_stage="BRONZE",
        root_cause_pattern="Transient failure for idempotency test",
        severity=AlertSeverityEnum.CRITICAL,
    )
    db.commit()

    # Move alert to RECOVERY_IN_PROGRESS
    AlertService.start_recovery(db=db, alert_id=alert.id, user_id="engineer")
    db.commit()

    idem_key = f"idem-lifecycle-{uuid.uuid4().hex}"
    action_payload = {
        "action_type": "RESTART_BATCH",
        "target_type": "BATCH",
        "target_id": str(batch.id),
        "parameters": {"alert_id": str(alert.id)},
        "reason": "Idempotent recovery action",
        "idempotency_key": idem_key,
    }

    # First call: executes and completes successfully
    res1 = client.post("/api/v1/ops/actions", json=action_payload, headers=engineer_headers)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "COMPLETED"

    db.refresh(alert)
    assert alert.status == AlertStatusEnum.RESOLVED

    # Second call (replay with same key): returns cached action without error
    res2 = client.post("/api/v1/ops/actions", json=action_payload, headers=engineer_headers)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["id"] == data1["id"]
    assert data2["status"] == "COMPLETED"

    # Batch restart count remains 1 (did not execute twice)
    db.refresh(batch)
    assert batch.restart_count == 1
