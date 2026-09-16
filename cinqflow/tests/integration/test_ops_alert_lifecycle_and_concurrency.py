"""
Integration tests for Alert Recovery Lifecycle, Historical Playbook Version Binding, and Concurrency Protection
Wave 2 Slice 4 Blockers 5, 7, 8
"""
import uuid
import hashlib
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy.orm import sessionmaker

from backend.models.incident import (
    OperationalAlert,
    AlertOccurrence,
    FailureFingerprint,
    RecoveryPlaybook,
    RecoveryPlaybookVersion,
    FailureCategoryEnum,
    AlertStatusEnum,
    AlertSeverityEnum,
    PlaybookStatusEnum,
)
from backend.models.pipeline import (
    Batch,
    BatchStatusEnum,
    BatchStage,
    StageNameEnum,
    StageStatusEnum,
    WAVE0_STAGE_ORDER,
)
from backend.models.feed import Feed, FeedFormatEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.input_registry import InputRegistry, InputStatusEnum
from backend.models.ops_action import ActionTypeEnum, ActionStatusEnum
from backend.adapters.storage import get_storage_adapter
from backend.services.alert_service import AlertService
from backend.services.playbook_service import PlaybookService
from backend.services.ops_action_service import OpsActionService
from backend.schemas.ops_action import OpsActionSubmitRequest


@pytest.fixture
def sample_feed(db):
    feed = Feed(
        id=uuid.uuid4(),
        name=f"test_feed_lifecycle_{uuid.uuid4().hex[:6]}",
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
        created_by="test",
        updated_by="test",
    )
    db.add(fv)
    db.flush()
    feed.active_version_id = fv.id
    db.flush()
    return feed


def test_complete_alert_recovery_lifecycle(client, engineer_headers, db, sample_feed):
    """
    Blocker 5: Full alert lifecycle state machine:
    OPEN -> ACKNOWLEDGED -> RECOVERY_IN_PROGRESS -> execute action -> action completes -> RESOLVED.
    """
    # 1. Setup failed batch with input file and stages
    storage = get_storage_adapter()
    file_bytes = b"member_id,first_name,last_name,date_of_birth,gender\nM001,John,Doe,1980-01-01,M\n"
    file_path = f"./data/landing/lifecycle_sample_{uuid.uuid4().hex[:8]}.csv"
    storage.write_file(file_path, file_bytes)

    inp = InputRegistry(
        id=uuid.uuid4(),
        feed_id=sample_feed.id,
        filename="test.csv",
        file_path=file_path,
        file_size_bytes=len(file_bytes),
        file_fingerprint=hashlib.sha256(file_bytes).hexdigest(),
        status=InputStatusEnum.ACCEPTED,
        registered_by="test",
        detected_at=datetime.now(timezone.utc),
        created_by="test",
        updated_by="test",
    )
    db.add(inp)
    db.flush()

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=sample_feed.id,
        feed_version_id=sample_feed.versions[0].id,
        input_registry_id=inp.id,
        status=BatchStatusEnum.FAILED,
        triggered_by="test",
        created_by="test",
        updated_by="test",
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
            created_by="test",
            updated_by="test",
        )
        db.add(stage)
    db.commit()

    # 2. Setup playbook with standard restart action
    pb = PlaybookService.create_playbook(
        db=db,
        title="Stage Failure Playbook",
        category=FailureCategoryEnum.STAGE_EXECUTION,
        playbook_code=f"PB-LIFECYCLE-{uuid.uuid4().hex[:6]}",
        explanation_template="Restart failed batch",
        suggested_action_type=ActionTypeEnum.RESTART_BATCH,
    )
    PlaybookService.approve_playbook_version(db=db, version_id=pb.current_version_id, approved_by="test")

    # 3. Create initial alert (OPEN)
    alert = AlertService.record_failure(
        db=db,
        feed_id=sample_feed.id,
        batch_id=batch.id,
        category=FailureCategoryEnum.STAGE_EXECUTION,
        failure_stage="BRONZE",
        root_cause_pattern="Connection timeout in Bronze copy",
        severity=AlertSeverityEnum.CRITICAL,
        user_id="pipeline-executor",
    )
    db.commit()
    assert alert.status == AlertStatusEnum.OPEN

    # 4. Operator Acknowledges Alert -> ACKNOWLEDGED
    ack_res = client.post(f"/api/v1/ops/alerts/{alert.id}/acknowledge", headers=engineer_headers)
    assert ack_res.status_code == 200
    assert ack_res.json()["status"] == "ACKNOWLEDGED"

    # 5. Check action proposal
    prop_res = client.get(f"/api/v1/ops/alerts/{alert.id}/action-proposal", headers=engineer_headers)
    assert prop_res.status_code == 200
    prop_data = prop_res.json()
    assert prop_data["is_executable"] is True
    assert prop_data["action_type"] == "RESTART_BATCH"
    assert prop_data["target_type"] == "BATCH"
    assert prop_data["target_id"] == str(batch.id)

    # 6. Execute playbook action via 1-click endpoint -> RECOVERY_IN_PROGRESS -> Auto-RESOLVED
    exec_res = client.post(f"/api/v1/ops/alerts/{alert.id}/execute-playbook", headers=engineer_headers)
    assert exec_res.status_code == 200
    exec_data = exec_res.json()
    assert exec_data["status"] == "COMPLETED"

    # 7. Check alert status in DB: must be automatically RESOLVED!
    resolved_alert = AlertService.get_alert_detail(db=db, alert_id=alert.id)
    assert resolved_alert.status == AlertStatusEnum.RESOLVED
    assert "Resolved automatically by successful recovery action" in resolved_alert.resolution_notes


def test_historical_playbook_version_binding(db, sample_feed):
    """
    Blocker 7: Historical playbook version binding:
    Existing alerts must retain their historical playbook version even after a new version is created and approved.
    """
    # 1. Create Playbook Version 1
    code = f"PB-HISTORICAL-{uuid.uuid4().hex[:6]}"
    pb = PlaybookService.create_playbook(
        db=db,
        title="Drift Remediation Playbook",
        category=FailureCategoryEnum.SCHEMA_DRIFT,
        playbook_code=code,
        explanation_template="Version 1: Old drift remediation instructions",
        suggested_action_type=ActionTypeEnum.RESTART_BATCH,
    )
    v1_id = pb.current_version_id
    PlaybookService.approve_playbook_version(db=db, version_id=v1_id, approved_by="test")
    db.commit()

    # 2. Record failure creating Alert 1 under Version 1
    alert1 = AlertService.record_failure(
        db=db,
        feed_id=sample_feed.id,
        category=FailureCategoryEnum.SCHEMA_DRIFT,
        failure_stage="LANDING",
        root_cause_pattern="Unexpected column 'patient_phone'",
        severity=AlertSeverityEnum.CRITICAL,
        user_id="executor",
    )
    db.commit()

    assert alert1.recommended_playbook_version_id == v1_id
    assert alert1.recommended_playbook_version.version_number == 1
    assert "Version 1" in alert1.recommended_playbook_version.explanation_template

    # 3. Create and approve Version 2
    v2 = PlaybookService.update_playbook(
        db=db,
        playbook_id=pb.id,
        explanation_template="Version 2: Brand new updated drift instructions with schema evolution",
        suggested_action_type=ActionTypeEnum.RETRIGGER_BATCH,
        user_id="test",
    )
    PlaybookService.approve_playbook_version(db=db, version_id=v2.id, approved_by="test")
    db.commit()

    # 4. Query Alert 1 again: IT MUST STILL BE BOUND TO VERSION 1!
    alert1_reloaded = AlertService.get_alert_detail(db=db, alert_id=alert1.id)
    assert alert1_reloaded.recommended_playbook_version_id == v1_id
    assert alert1_reloaded.recommended_playbook_version.version_number == 1
    assert "Version 1" in alert1_reloaded.recommended_playbook_version.explanation_template

    other_feed = Feed(
        id=uuid.uuid4(),
        name=f"other_feed_{uuid.uuid4().hex[:6]}",
        domain="MEMBERS",
        format=FeedFormatEnum.CSV,
        landing_folder="./data/landing/other",
        filename_pattern="*.csv",
        created_by="test",
        updated_by="test",
    )
    db.add(other_feed)
    db.flush()

    alert2 = AlertService.record_failure(
        db=db,
        feed_id=other_feed.id,
        category=FailureCategoryEnum.SCHEMA_DRIFT,
        failure_stage="LANDING",
        root_cause_pattern="Unexpected column 'new_col'",
        severity=AlertSeverityEnum.CRITICAL,
        user_id="executor",
    )
    db.commit()

    assert alert2.recommended_playbook_version_id == v2.id
    assert alert2.recommended_playbook_version.version_number == 2
    assert "Version 2" in alert2.recommended_playbook_version.explanation_template


def test_concurrency_protection_two_workers_same_failure():
    """
    Blocker 8: Two workers reporting the exact same failure concurrently must:
    - Result in exactly 1 alert in the database.
    - Have occurrence_count == 2.
    - Zero crashes or unhandled IntegrityErrors.
    """
    from tests.conftest import TestSessionLocal

    # Setup feed directly in TestSessionLocal on test database
    init_db = TestSessionLocal()
    feed = Feed(
        id=uuid.uuid4(),
        name=f"test_feed_concurrent_{uuid.uuid4().hex[:6]}",
        domain="MEMBERS",
        format=FeedFormatEnum.CSV,
        landing_folder="./data/landing/test",
        filename_pattern="*.csv",
        created_by="test",
        updated_by="test",
    )
    init_db.add(feed)
    fv = FeedVersion(
        id=uuid.uuid4(),
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="test",
        updated_by="test",
    )
    init_db.add(fv)
    init_db.commit()
    feed_id = feed.id
    init_db.close()

    pattern = f"Concurrent deadlock test pattern {uuid.uuid4().hex}"

    results = []
    errors = []

    def worker_report(worker_id: int):
        thread_db = TestSessionLocal()
        try:
            alert = AlertService.record_failure(
                db=thread_db,
                feed_id=feed_id,
                category=FailureCategoryEnum.STAGE_EXECUTION,
                failure_stage="LANDING",
                root_cause_pattern=pattern,
                severity=AlertSeverityEnum.CRITICAL,
                user_id=f"worker-{worker_id}",
            )
            thread_db.commit()
            results.append(str(alert.id))
        except Exception as e:
            thread_db.rollback()
            errors.append(e)
        finally:
            thread_db.close()

    # Launch two workers concurrently
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker_report, i) for i in range(1, 3)]
        for f in futures:
            f.result()

    # Zero exceptions
    assert len(errors) == 0
    assert len(results) == 2

    # Both workers must reference the EXACT SAME alert ID!
    assert results[0] == results[1]

    # Verify single alert with occurrence_count == 2
    verify_db = TestSessionLocal()
    try:
        alert_id = uuid.UUID(results[0])
        alert = verify_db.query(OperationalAlert).filter(OperationalAlert.id == alert_id).first()
        assert alert is not None
        assert alert.occurrence_count == 2
        assert len(alert.occurrences) == 2

        # Cleanup test records
        verify_db.query(AlertOccurrence).filter(AlertOccurrence.alert_id == alert_id).delete()
        verify_db.query(OperationalAlert).filter(OperationalAlert.id == alert_id).delete()
        verify_db.query(FeedVersion).filter(FeedVersion.feed_id == feed_id).delete()
        verify_db.query(Feed).filter(Feed.id == feed_id).delete()
        verify_db.commit()
    finally:
        verify_db.close()
