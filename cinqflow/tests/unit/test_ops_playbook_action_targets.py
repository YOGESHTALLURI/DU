"""
Unit tests for Governed Playbook Action Targets & Safety Preconditions
Wave 2 Slice 4 Blockers 1, 2, 6
"""
import uuid
import pytest
from fastapi import HTTPException

from backend.models.ops_action import ActionTypeEnum, ActionRiskLevelEnum, ActionStatusEnum
from backend.models.pipeline import Batch, BatchStatusEnum
from backend.models.schedule import FeedSchedule, ScheduleStatusEnum
from backend.models.input_registry import QuarantineRecord, QuarantineStatusEnum, QuarantineReasonEnum
from backend.models.incident import (
    RecoveryPlaybook,
    RecoveryPlaybookVersion,
    OperationalAlert,
    FailureFingerprint,
    FailureCategoryEnum,
    AlertStatusEnum,
    AlertSeverityEnum,
    PlaybookStatusEnum,
)
from backend.models.feed import Feed, FeedFormatEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.user import User, RoleEnum, AuthProviderEnum
from backend.services.ops_action_service import OpsActionService, ACTION_TARGET_MAPPING
from backend.services.playbook_service import PlaybookService
from backend.schemas.ops_action import OpsActionSubmitRequest


@pytest.fixture
def test_engineer(db):
    user = User(
        id=uuid.uuid4(),
        email=f"engineer_{uuid.uuid4().hex[:6]}@cinqflow.test",
        full_name="Test Engineer",
        auth_provider=AuthProviderEnum.mock,
        auth_provider_id=f"mock-{uuid.uuid4().hex[:6]}",
        is_active=True,
        created_by="test",
        updated_by="test",
    )
    db.add(user)
    db.flush()
    from backend.models.user import Role, UserRole
    eng_role = db.query(Role).filter(Role.name == RoleEnum.ENGINEER).first()
    if not eng_role:
        eng_role = Role(id=uuid.uuid4(), name=RoleEnum.ENGINEER, created_by="test", updated_by="test")
        db.add(eng_role)
        db.flush()
    db.add(UserRole(user_id=user.id, role=RoleEnum.ENGINEER, role_id=eng_role.id, created_by="test", updated_by="test"))
    db.flush()
    return user


@pytest.fixture
def sample_feed(db):
    feed = Feed(
        id=uuid.uuid4(),
        name=f"test_feed_{uuid.uuid4().hex[:6]}",
        domain="MEMBERS",
        format=FeedFormatEnum.CSV,
        landing_folder="./data/landing/test",
        filename_pattern="*.csv",
        created_by="test",
        updated_by="test",
    )
    db.add(feed)
    db.flush()

    fv = FeedVersion(
        id=uuid.uuid4(),
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="test",
        updated_by="test",
    )
    db.add(fv)
    db.flush()
    return feed


def test_action_target_mapping_authoritative_enforcement(db):
    """Blocker 1: Action-to-target mapping must strictly reject invalid targets with HTTP 400."""
    service = OpsActionService(db)

    # Valid combinations must pass
    OpsActionService.validate_action_target_mapping(ActionTypeEnum.RESTART_BATCH, "BATCH")
    OpsActionService.validate_action_target_mapping(ActionTypeEnum.RETRIGGER_BATCH, "BATCH")
    OpsActionService.validate_action_target_mapping(ActionTypeEnum.PAUSE_SCHEDULE, "FEED_SCHEDULE")
    OpsActionService.validate_action_target_mapping(ActionTypeEnum.RESUME_SCHEDULE, "FEED_SCHEDULE")
    OpsActionService.validate_action_target_mapping(ActionTypeEnum.REPROCESS_QUARANTINE, "QUARANTINE_RECORD")
    OpsActionService.validate_action_target_mapping(ActionTypeEnum.DISCARD_QUARANTINE, "QUARANTINE_RECORD")

    # Invalid combinations must raise 400
    with pytest.raises(HTTPException) as exc1:
        OpsActionService.validate_action_target_mapping(ActionTypeEnum.PAUSE_SCHEDULE, "BATCH")
    assert exc1.value.status_code == 400
    assert "Invalid target_type 'BATCH' for action_type 'PAUSE_SCHEDULE'" in exc1.value.detail

    with pytest.raises(HTTPException) as exc2:
        OpsActionService.validate_action_target_mapping(ActionTypeEnum.RESTART_BATCH, "FEED_SCHEDULE")
    assert exc2.value.status_code == 400

    with pytest.raises(HTTPException) as exc3:
        OpsActionService.validate_action_target_mapping(ActionTypeEnum.REPROCESS_QUARANTINE, "BATCH")
    assert exc3.value.status_code == 400


def test_safety_preconditions_restart_batch_on_success_rejected(db, sample_feed, test_engineer):
    """Blocker 2: Attempting RESTART_BATCH on a SUCCESS batch must fail safety preconditions with 400."""
    batch = Batch(
        id=uuid.uuid4(),
        feed_id=sample_feed.id,
        feed_version_id=sample_feed.versions[0].id,
        status=BatchStatusEnum.SUCCESS,
        triggered_by="test",
        created_by="test",
        updated_by="test",
    )
    db.add(batch)
    db.flush()

    service = OpsActionService(db)

    with pytest.raises(HTTPException) as exc:
        service.validate_safety_preconditions(
            action_type=ActionTypeEnum.RESTART_BATCH,
            target_type="BATCH",
            target_id=str(batch.id),
            parameters={},
        )
    assert exc.value.status_code == 400
    assert "RESTART_BATCH requires FAILED or FAILED_RECONCILIATION" in exc.value.detail


def test_safety_preconditions_retrigger_batch_on_failed_rejected(db, sample_feed, test_engineer):
    """Blocker 2: Attempting RETRIGGER_BATCH on a FAILED batch must fail safety preconditions with 400."""
    batch = Batch(
        id=uuid.uuid4(),
        feed_id=sample_feed.id,
        feed_version_id=sample_feed.versions[0].id,
        status=BatchStatusEnum.FAILED,
        triggered_by="test",
        created_by="test",
        updated_by="test",
    )
    db.add(batch)
    db.flush()

    service = OpsActionService(db)

    with pytest.raises(HTTPException) as exc:
        service.validate_safety_preconditions(
            action_type=ActionTypeEnum.RETRIGGER_BATCH,
            target_type="BATCH",
            target_id=str(batch.id),
            parameters={},
        )
    assert exc.value.status_code == 400
    assert "RETRIGGER_BATCH requires SUCCESS" in exc.value.detail


def test_safety_preconditions_pause_already_paused_schedule_rejected(db, sample_feed, test_engineer):
    """Blocker 2: Attempting PAUSE_SCHEDULE on a PAUSED schedule must fail safety preconditions with 400."""
    sched = FeedSchedule(
        id=uuid.uuid4(),
        feed_id=sample_feed.id,
        schedule_expression="0 0 * * *",
        timezone="UTC",
        status=ScheduleStatusEnum.PAUSED,
        created_by="test",
        updated_by="test",
    )
    db.add(sched)
    db.flush()

    service = OpsActionService(db)

    with pytest.raises(HTTPException) as exc:
        service.validate_safety_preconditions(
            action_type=ActionTypeEnum.PAUSE_SCHEDULE,
            target_type="FEED_SCHEDULE",
            target_id=str(sched.id),
            parameters={},
        )
    assert exc.value.status_code == 400
    assert "PAUSE_SCHEDULE requires ACTIVE" in exc.value.detail


def test_safety_preconditions_resume_already_active_schedule_rejected(db, sample_feed, test_engineer):
    """Blocker 2: Attempting RESUME_SCHEDULE on an ACTIVE schedule must fail safety preconditions with 400."""
    sched = FeedSchedule(
        id=uuid.uuid4(),
        feed_id=sample_feed.id,
        schedule_expression="0 0 * * *",
        timezone="UTC",
        status=ScheduleStatusEnum.ACTIVE,
        created_by="test",
        updated_by="test",
    )
    db.add(sched)
    db.flush()

    service = OpsActionService(db)

    with pytest.raises(HTTPException) as exc:
        service.validate_safety_preconditions(
            action_type=ActionTypeEnum.RESUME_SCHEDULE,
            target_type="FEED_SCHEDULE",
            target_id=str(sched.id),
            parameters={},
        )
    assert exc.value.status_code == 400
    assert "RESUME_SCHEDULE requires PAUSED" in exc.value.detail


def test_category_fallback_safety_precondition_evaluation(db, sample_feed):
    """Blocker 6: Playbook suggested action evaluated when target state is invalid must be marked unexecutable with blocking reason."""
    # Playbook suggests REPROCESS_QUARANTINE
    pb = PlaybookService.create_playbook(
        db=db,
        title="Quarantine Fallback Playbook",
        category=FailureCategoryEnum.DATA_QUALITY,
        playbook_code=f"PB-TEST-DQ-FALLBACK-{uuid.uuid4().hex[:6]}",
        explanation_template="Quarantine recovery steps",
        suggested_action_type=ActionTypeEnum.REPROCESS_QUARANTINE,
    )
    PlaybookService.approve_playbook_version(db=db, version_id=pb.current_version_id, approved_by="test")

    # Alert on a batch with NO quarantine records
    batch = Batch(
        id=uuid.uuid4(),
        feed_id=sample_feed.id,
        feed_version_id=sample_feed.versions[0].id,
        status=BatchStatusEnum.FAILED,
        triggered_by="test",
        created_by="test",
        updated_by="test",
    )
    db.add(batch)
    db.flush()

    fp = FailureFingerprint(
        id=uuid.uuid4(),
        category=FailureCategoryEnum.DATA_QUALITY,
        root_cause_pattern="Test DQ failure",
        canonical_signature="{}",
        fingerprint_hash=uuid.uuid4().hex,
        total_occurrences=1,
        created_by="test",
        updated_by="test",
    )
    db.add(fp)
    db.flush()

    alert = OperationalAlert(
        id=uuid.uuid4(),
        feed_id=sample_feed.id,
        batch_id=batch.id,
        failure_fingerprint_id=fp.id,
        recommended_playbook_version_id=pb.current_version_id,
        title="Test DQ Alert",
        description="Test",
        severity=AlertSeverityEnum.CRITICAL,
        status=AlertStatusEnum.OPEN,
        occurrence_count=1,
        created_by="test",
        updated_by="test",
    )
    db.add(alert)
    db.flush()

    # Precondition evaluation must return is_executable=False with clear blocking reason
    proposal = PlaybookService.evaluate_playbook_preconditions(
        db=db,
        playbook_version=pb.current_version,
        alert=alert,
    )

    assert proposal["is_executable"] is False
    assert proposal["action_type"] == ActionTypeEnum.REPROCESS_QUARANTINE
    assert "No active QUARANTINED records found" in proposal["blocking_reason"]
