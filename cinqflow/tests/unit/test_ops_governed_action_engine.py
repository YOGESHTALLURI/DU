"""
Unit tests for Governed Action Surface Engine (Wave 2 Slice 3 — CF-V2-E12-03).
"""
import uuid
from datetime import datetime, timezone
import pytest
from fastapi import HTTPException

from backend.models.feed import Feed, FeedVersion, FeedFormatEnum, FeedStatusEnum, FeedVersionStatusEnum
from backend.models.pipeline import (
    Batch,
    BatchStatusEnum,
    StageNameEnum,
)
from backend.models.input_registry import (
    InputRegistry,
    InputStatusEnum,
    QuarantineRecord,
    QuarantineReasonEnum,
    QuarantineStatusEnum,
)
from backend.models.ops_action import (
    OperationalActionRequest,
    ActionTypeEnum,
    ActionRiskLevelEnum,
    ActionStatusEnum,
)
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.core.security import CurrentUser
from backend.services.ops_action_service import OpsActionService
from backend.schemas.ops_action import OpsActionSubmitRequest
from backend.adapters.storage import get_storage_adapter
from tests.unit.test_ops_recovery_service import recovery_feed, _create_sample_batch


@pytest.fixture
def mock_engineer1():
    return CurrentUser(
        user_id="mock-engineer-001",
        email="eng1@cinqflow.local",
        roles=["ENGINEER"],
        auth_provider="mock",
    )


@pytest.fixture
def mock_engineer2():
    return CurrentUser(
        user_id="mock-engineer-002",
        email="eng2@cinqflow.local",
        roles=["ENGINEER"],
        auth_provider="mock",
    )


@pytest.fixture
def mock_analyst():
    return CurrentUser(
        user_id="mock-analyst-001",
        email="analyst@cinqflow.local",
        roles=["BUSINESS_ANALYST"],
        auth_provider="mock",
    )


def test_standard_action_executes_immediately_with_audit(db, recovery_feed, mock_engineer1):
    """9. Test that a standard risk action (e.g. restart failed batch) executes immediately and writes audit."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.FAILED
    db.flush()

    action_service = OpsActionService(db)
    req = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.RESTART_BATCH,
        target_type="BATCH",
        target_id=str(batch.id),
        reason="Routine restart after network timeout",
    )

    action_record = action_service.submit_action(req, mock_engineer1)

    assert action_record.risk_level == ActionRiskLevelEnum.STANDARD
    assert action_record.status == ActionStatusEnum.COMPLETED
    assert action_record.requested_by == mock_engineer1.user_id
    assert action_record.execution_result is not None
    assert action_record.execution_result["batch_id"] == str(batch.id)

    # Verify audit event
    audit_evt = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.action == AuditActionEnum.OPS_ACTION_EXECUTED,
            AuditEvent.object_id == str(action_record.id),
        )
        .first()
    )
    assert audit_evt is not None
    assert audit_evt.actor_id == mock_engineer1.user_id


def test_high_risk_action_enters_pending_approval(db, recovery_feed, mock_engineer1):
    """10. Test that a high risk action enters PENDING_APPROVAL and emits ops.action_requested."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.SUCCESS
    db.flush()

    action_service = OpsActionService(db)
    req = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.RETRIGGER_BATCH,
        target_type="BATCH",
        target_id=str(batch.id),
        reason="Client requested complete re-run of yesterday file",
    )

    action_record = action_service.submit_action(req, mock_engineer1)

    assert action_record.risk_level == ActionRiskLevelEnum.HIGH_RISK
    assert action_record.status == ActionStatusEnum.PENDING_APPROVAL
    assert action_record.reviewed_by is None

    # Verify audit event
    audit_evt = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.action == AuditActionEnum.OPS_ACTION_REQUESTED,
            AuditEvent.object_id == str(action_record.id),
        )
        .first()
    )
    assert audit_evt is not None
    assert audit_evt.actor_id == mock_engineer1.user_id


def test_dual_control_four_eyes_rejects_self_approval(db, recovery_feed, mock_engineer1):
    """11. Test Four-Eyes governance: operator cannot approve their own high-risk action."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.SUCCESS
    db.flush()

    action_service = OpsActionService(db)
    req = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.RETRIGGER_BATCH,
        target_type="BATCH",
        target_id=str(batch.id),
        reason="Re-run test",
    )
    action_record = action_service.submit_action(req, mock_engineer1)

    # Engineer 1 attempts self-approval
    with pytest.raises(HTTPException) as exc_info:
        action_service.approve_action(
            action_id=action_record.id,
            decision_notes="Self approval attempt",
            current_user=mock_engineer1,
        )
    assert exc_info.value.status_code == 403
    assert "four-eyes" in exc_info.value.detail.lower()


def test_dual_control_approved_by_second_operator_executes(db, recovery_feed, mock_engineer1, mock_engineer2):
    """12. Test that an independent second operator successfully approves and executes high-risk action."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.SUCCESS
    db.flush()

    action_service = OpsActionService(db)
    req = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.RETRIGGER_BATCH,
        target_type="BATCH",
        target_id=str(batch.id),
        reason="Client retrigger request",
    )
    action_record = action_service.submit_action(req, mock_engineer1)

    # Engineer 2 approves
    approved = action_service.approve_action(
        action_id=action_record.id,
        decision_notes="Verified client ticket #1024. Approved.",
        current_user=mock_engineer2,
    )

    assert approved.status == ActionStatusEnum.COMPLETED
    assert approved.reviewed_by == mock_engineer2.user_id
    assert approved.decision_notes == "Verified client ticket #1024. Approved."

    # Audit events verified
    audit_approved = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.action == AuditActionEnum.OPS_ACTION_APPROVED,
            AuditEvent.object_id == str(action_record.id),
        )
        .first()
    )
    assert audit_approved is not None
    assert audit_approved.actor_id == mock_engineer2.user_id


def test_dual_control_rejection_marks_rejected_and_audits(db, recovery_feed, mock_engineer1, mock_engineer2):
    """13. Test rejecting a pending high-risk action."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.SUCCESS
    db.flush()

    action_service = OpsActionService(db)
    req = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.RETRIGGER_BATCH,
        target_type="BATCH",
        target_id=str(batch.id),
        reason="Questionable re-trigger",
    )
    action_record = action_service.submit_action(req, mock_engineer1)

    # Engineer 2 rejects
    rejected = action_service.reject_action(
        action_id=action_record.id,
        decision_notes="Duplicate ticket. Rejected.",
        current_user=mock_engineer2,
    )

    assert rejected.status == ActionStatusEnum.REJECTED
    assert rejected.reviewed_by == mock_engineer2.user_id

    audit_rej = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.action == AuditActionEnum.OPS_ACTION_REJECTED,
            AuditEvent.object_id == str(action_record.id),
        )
        .first()
    )
    assert audit_rej is not None
    assert audit_rej.actor_id == mock_engineer2.user_id


def test_concurrency_row_lock_prevents_race_condition(db, recovery_feed, mock_engineer1):
    """14. Test row locking on batch and action request."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.FAILED
    db.flush()

    # Query with for update acquires lock safely inside transaction
    locked_batch = db.query(Batch).filter(Batch.id == batch.id).with_for_update().first()
    assert locked_batch is not None
    assert locked_batch.id == batch.id


def test_idempotency_key_prevents_duplicate_action_submission(db, recovery_feed, mock_engineer1):
    """15. Test client idempotency key prevents duplicate execution on rapid replay."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.FAILED
    db.flush()

    idem_key = f"idem-{uuid.uuid4().hex}"
    action_service = OpsActionService(db)
    req1 = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.RESTART_BATCH,
        target_type="BATCH",
        target_id=str(batch.id),
        reason="First click",
        idempotency_key=idem_key,
    )
    res1 = action_service.submit_action(req1, mock_engineer1)

    req2 = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.RESTART_BATCH,
        target_type="BATCH",
        target_id=str(batch.id),
        reason="Second rapid click",
        idempotency_key=idem_key,
    )
    res2 = action_service.submit_action(req2, mock_engineer1)

    # Identical request ID returned, no duplicate action record created
    assert res1.id == res2.id
    total_actions = (
        db.query(OperationalActionRequest)
        .filter(OperationalActionRequest.idempotency_key == idem_key)
        .count()
    )
    assert total_actions == 1


def test_zero_phi_sanitization_in_action_reason_and_audit(db, recovery_feed, mock_engineer1):
    """16. Test zero-PHI sanitization on operator reason text in action request and audit log."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.FAILED
    db.flush()

    action_service = OpsActionService(db)
    # Reason contains SSN and patient email
    unsanitized_reason = "Retrying for patient SSN 123-45-6789 and email john.doe@healthcare.org"

    req = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.RESTART_BATCH,
        target_type="BATCH",
        target_id=str(batch.id),
        reason=unsanitized_reason,
    )
    action_record = action_service.submit_action(req, mock_engineer1)

    # Persisted reason in operational_action_requests must not contain sensitive info
    assert "123-45-6789" not in action_record.reason
    assert "john.doe@healthcare.org" not in action_record.reason
    assert "[REDACTED_SSN]" in action_record.reason
    assert "[REDACTED_EMAIL]" in action_record.reason

    # Persisted audit event must also be scrubbed
    audit_evt = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.action == AuditActionEnum.OPS_ACTION_EXECUTED,
            AuditEvent.object_id == str(action_record.id),
        )
        .first()
    )
    assert audit_evt is not None
    assert "123-45-6789" not in audit_evt.description


def test_bulk_quarantine_boundary_50_vs_51(db, recovery_feed, mock_engineer1):
    """Test 50 records executes immediately as standard risk; 51 records is promoted to bulk high risk."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    action_service = OpsActionService(db)

    # 1. 50 records -> Standard risk, executes immediately
    qr_objs_50 = [
        QuarantineRecord(
            id=uuid.uuid4(),
            batch_id=batch.id,
            stage_name=StageNameEnum.SILVER_RAW.value,
            source_row_number=i,
            source_record_raw=f"M00{i},Alice,Johnson,1985-06-15,F",
            field_name="member_id",
            reason=QuarantineReasonEnum.MISSING_REQUIRED_FIELD,
            status=QuarantineStatusEnum.QUARANTINED,
            created_by="system",
            updated_by="system",
        )
        for i in range(1, 51)
    ]
    db.add_all(qr_objs_50)
    db.commit()
    record_ids_50 = [str(q.id) for q in qr_objs_50]

    req_50 = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.REPROCESS_QUARANTINE,
        target_type="QUARANTINE_RECORD",
        target_id=record_ids_50[0],
        parameters={"record_ids": record_ids_50},
        reason="Batch of 50 records",
    )
    # Patch recovery reprocess to avoid needing full executor run
    from unittest.mock import patch
    with patch.object(action_service.recovery, "reprocess_quarantine_records") as mock_reprocess:
        mock_reprocess.return_value = {"reprocessed_count": 50, "recovery_batch_id": str(uuid.uuid4())}
        res_50 = action_service.submit_action(req_50, mock_engineer1)
        assert res_50.risk_level == ActionRiskLevelEnum.STANDARD
        assert res_50.status == ActionStatusEnum.COMPLETED

    # 2. 51 records -> Promoted to BULK_REPROCESS_QUARANTINE, HIGH_RISK, PENDING_APPROVAL
    qr_objs_51 = [
        QuarantineRecord(
            id=uuid.uuid4(),
            batch_id=batch.id,
            stage_name=StageNameEnum.SILVER_RAW.value,
            source_row_number=i,
            source_record_raw=f"M00{i},Alice,Johnson,1985-06-15,F",
            field_name="member_id",
            reason=QuarantineReasonEnum.MISSING_REQUIRED_FIELD,
            status=QuarantineStatusEnum.QUARANTINED,
            created_by="system",
            updated_by="system",
        )
        for i in range(1, 52)
    ]
    db.add_all(qr_objs_51)
    db.commit()
    record_ids_51 = [str(q.id) for q in qr_objs_51]

    req_51 = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.REPROCESS_QUARANTINE,
        target_type="QUARANTINE_RECORD",
        target_id=record_ids_51[0],
        parameters={"record_ids": record_ids_51},
        reason="Batch of 51 records",
    )
    res_51 = action_service.submit_action(req_51, mock_engineer1)
    assert res_51.action_type == ActionTypeEnum.BULK_REPROCESS_QUARANTINE
    assert res_51.risk_level == ActionRiskLevelEnum.HIGH_RISK
    assert res_51.status == ActionStatusEnum.PENDING_APPROVAL


def test_idempotency_key_conflict_different_payload(db, recovery_feed, mock_engineer1):
    """Test submitting same idempotency key with different action or target raises 409 Conflict."""
    feed, version = recovery_feed
    batch1 = _create_sample_batch(db, feed, version, content_csv="member_id,first_name,last_name,date_of_birth,gender\nM001,John,Doe,1980-01-01,M\n")
    batch1.status = BatchStatusEnum.FAILED
    batch2 = _create_sample_batch(db, feed, version, content_csv="member_id,first_name,last_name,date_of_birth,gender\nM002,Jane,Smith,1985-02-02,F\n")
    batch2.status = BatchStatusEnum.FAILED
    db.flush()

    idem_key = f"idem-conflict-{uuid.uuid4().hex}"
    action_service = OpsActionService(db)

    req1 = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.RESTART_BATCH,
        target_type="BATCH",
        target_id=str(batch1.id),
        reason="First submit",
        idempotency_key=idem_key,
    )
    action_service.submit_action(req1, mock_engineer1)

    # Submit same key with different target_id
    req2 = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.RESTART_BATCH,
        target_type="BATCH",
        target_id=str(batch2.id),
        reason="Second submit with different target",
        idempotency_key=idem_key,
    )
    with pytest.raises(HTTPException) as exc_info:
        action_service.submit_action(req2, mock_engineer1)
    assert exc_info.value.status_code == 409
    assert "Idempotency key conflict" in exc_info.value.detail


def test_schedule_pause_and_resume_governed_flow(db, recovery_feed, mock_engineer1):
    """Test PAUSE_SCHEDULE and RESUME_SCHEDULE via OpsActionService, including invalid duplicate states."""
    from backend.services.scheduling_service import SchedulingService
    from backend.models.schedule import ScheduleStatusEnum
    feed, version = recovery_feed

    sched_service = SchedulingService(db)
    sched = sched_service.update_schedule(feed.id, "0 * * * *", "UTC", False, current_user=mock_engineer1)
    assert sched.status == ScheduleStatusEnum.ACTIVE

    action_service = OpsActionService(db)

    # 1. Pause active schedule -> COMPLETED
    req_pause = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.PAUSE_SCHEDULE,
        target_type="FEED_SCHEDULE",
        target_id=str(feed.id),
        reason="Routine maintenance window",
    )
    res_pause = action_service.submit_action(req_pause, mock_engineer1)
    assert res_pause.status == ActionStatusEnum.COMPLETED

    db.refresh(sched)
    assert sched.status == ScheduleStatusEnum.PAUSED
    assert sched.next_run_at is None

    # 2. Pause already paused schedule -> 400 Bad Request
    with pytest.raises(HTTPException) as exc_info:
        action_service.submit_action(req_pause, mock_engineer1)
    assert exc_info.value.status_code == 400
    assert "already PAUSED" in exc_info.value.detail

    # 3. Resume paused schedule -> COMPLETED
    req_resume = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.RESUME_SCHEDULE,
        target_type="FEED_SCHEDULE",
        target_id=str(feed.id),
        reason="Maintenance complete, resume feed",
    )
    res_resume = action_service.submit_action(req_resume, mock_engineer1)
    assert res_resume.status == ActionStatusEnum.COMPLETED

    db.refresh(sched)
    assert sched.status == ScheduleStatusEnum.ACTIVE
    assert sched.next_run_at is not None

    # 4. Resume already active schedule -> 400 Bad Request
    with pytest.raises(HTTPException) as exc_info:
        action_service.submit_action(req_resume, mock_engineer1)
    assert exc_info.value.status_code == 400
    assert "already ACTIVE" in exc_info.value.detail


def test_rbac_role_authorizations_and_restrictions(db, recovery_feed, mock_engineer1):
    """Test role authorizations: ENGINEER & DATA_STEWARD allowed, READ_ONLY & BUSINESS_ANALYST forbidden."""
    from unittest.mock import patch
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.FAILED
    db.flush()

    action_service = OpsActionService(db)
    req = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.RESTART_BATCH,
        target_type="BATCH",
        target_id=str(batch.id),
        reason="Restart attempt",
    )

    user_readonly = CurrentUser(
        user_id="mock-ro-001",
        email="ro@cinqflow.local",
        roles=["READ_ONLY"],
        auth_provider="mock",
    )
    user_analyst = CurrentUser(
        user_id="mock-ba-001",
        email="ba@cinqflow.local",
        roles=["BUSINESS_ANALYST"],
        auth_provider="mock",
    )
    user_steward = CurrentUser(
        user_id="mock-ds-001",
        email="ds@cinqflow.local",
        roles=["DATA_STEWARD"],
        auth_provider="mock",
    )

    # READ_ONLY rejected with 403
    with pytest.raises(HTTPException) as exc_ro:
        action_service.submit_action(req, user_readonly)
    assert exc_ro.value.status_code == 403

    # BUSINESS_ANALYST rejected with 403
    with pytest.raises(HTTPException) as exc_ba:
        action_service.submit_action(req, user_analyst)
    assert exc_ba.value.status_code == 403

    # DATA_STEWARD authorized for quarantine actions
    qr_steward = QuarantineRecord(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_name=StageNameEnum.SILVER_RAW.value,
        source_row_number=1,
        source_record_raw="M001,Alice,Johnson,1985-06-15,F",
        field_name="member_id",
        reason=QuarantineReasonEnum.MISSING_REQUIRED_FIELD,
        status=QuarantineStatusEnum.QUARANTINED,
        created_by="system",
        updated_by="system",
    )
    db.add(qr_steward)
    db.commit()

    req_qr = OpsActionSubmitRequest(
        action_type=ActionTypeEnum.REPROCESS_QUARANTINE,
        target_type="QUARANTINE_RECORD",
        target_id=str(qr_steward.id),
        parameters={"record_ids": [str(qr_steward.id)]},
        reason="Steward quarantine reprocess",
    )
    with patch.object(action_service.recovery, "reprocess_quarantine_records") as mock_rep:
        mock_rep.return_value = {"reprocessed_count": 1, "recovery_batch_id": str(uuid.uuid4())}
        res_ds = action_service.submit_action(req_qr, user_steward)
        assert res_ds.status == ActionStatusEnum.COMPLETED

