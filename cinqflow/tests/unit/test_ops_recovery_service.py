"""
Unit tests for OpsRecoveryService (Wave 2 Slice 3 — CF-V2-E8-04).
"""
import uuid
from datetime import datetime, timezone
import pytest
from fastapi import HTTPException

from backend.models.feed import Feed, FeedVersion, FeedFormatEnum, FeedStatusEnum, FeedVersionStatusEnum
from backend.models.pipeline import (
    Batch,
    BatchStage,
    BatchStatusEnum,
    StageNameEnum,
    StageStatusEnum,
    WAVE0_STAGE_ORDER,
)
from backend.models.input_registry import (
    InputRegistry,
    InputStatusEnum,
    QuarantineRecord,
    QuarantineReasonEnum,
    QuarantineStatusEnum,
)
from backend.models.dq_result import DQResult, DQActionTakenEnum
from backend.models.rule import RuleSeverityEnum
from backend.services.ops_recovery_service import OpsRecoveryService
from backend.engine.executor import PipelineExecutor
from backend.adapters.storage import get_storage_adapter


@pytest.fixture
def recovery_feed(db):
    feed = Feed(
        name="RECOVERY_UNIT_FEED",
        domain="CLAIMS",
        description="Feed for unit testing OpsRecoveryService",
        format=FeedFormatEnum.CSV,
        landing_folder="./data/landing/recovery_feed",
        filename_pattern="RECOVERY_*.csv",
        schedule_expression="manual",
        status=FeedStatusEnum.ACTIVE,
        created_by="system",
        updated_by="system",
    )
    db.add(feed)
    db.flush()

    version = FeedVersion(
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
        created_by="system",
        updated_by="system",
    )
    db.add(version)
    db.flush()
    feed.active_version_id = version.id
    db.flush()
    return feed, version


def _create_sample_batch(db, feed, version, content_csv=None):
    storage = get_storage_adapter()
    if content_csv is None:
        content_csv = "member_id,first_name,last_name,date_of_birth,gender\nM001,John,Doe,1980-01-01,M\n"
    
    file_bytes = content_csv.encode("utf-8")
    import hashlib
    fp = hashlib.sha256(file_bytes).hexdigest()
    file_path = f"./data/landing/recovery_feed/test_{uuid.uuid4().hex[:8]}.csv"
    storage.write_file(file_path, file_bytes)

    inp = InputRegistry(
        id=uuid.uuid4(),
        feed_id=feed.id,
        filename=f"test_{uuid.uuid4().hex[:8]}.csv",
        file_path=file_path,
        file_size_bytes=len(file_bytes),
        file_fingerprint=fp,
        status=InputStatusEnum.ACCEPTED,
        registered_by="system",
        detected_at=datetime.now(timezone.utc),
        created_by="system",
        updated_by="system",
    )
    db.add(inp)
    db.flush()

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=version.id,
        input_registry_id=inp.id,
        status=BatchStatusEnum.PENDING,
        triggered_by="test",
        created_by="system",
        updated_by="system",
    )
    db.add(batch)
    db.flush()
    return batch


def test_restart_failed_batch_skips_completed_stages(db, recovery_feed):
    """1. Test that restarting a failed batch resumes from the failed stage and skips completed stages."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)

    executor = PipelineExecutor(db)
    # Simulate failure at SILVER_RAW
    batch = executor.execute_batch(
        batch_id=batch.id,
        actor_id="eng1",
        simulate_failure_stage=StageNameEnum.SILVER_RAW,
    )
    assert batch.status == BatchStatusEnum.FAILED
    assert batch.get_stage(StageNameEnum.LANDING).status == StageStatusEnum.SUCCESS
    assert batch.get_stage(StageNameEnum.BRONZE).status == StageStatusEnum.SUCCESS
    assert batch.get_stage(StageNameEnum.SILVER_RAW).status == StageStatusEnum.FAILED

    landing_completed_at = batch.get_stage(StageNameEnum.LANDING).completed_at
    bronze_completed_at = batch.get_stage(StageNameEnum.BRONZE).completed_at

    # Restart
    recovery_service = OpsRecoveryService(db)
    res_batch = recovery_service.restart_failed_batch(
        batch_id=batch.id,
        actor_id="eng2",
        reason="Retrying failed silver stage after transient issue",
    )

    assert res_batch.status == BatchStatusEnum.SUCCESS
    assert res_batch.restart_count == 1
    # Check that Landing and Bronze completion timestamps are unchanged (skipped)
    assert res_batch.get_stage(StageNameEnum.LANDING).completed_at == landing_completed_at
    assert res_batch.get_stage(StageNameEnum.BRONZE).completed_at == bronze_completed_at
    assert res_batch.get_stage(StageNameEnum.SILVER_RAW).status == StageStatusEnum.SUCCESS


def test_restart_cleans_up_prior_stage_artifacts_and_dq_results(db, recovery_feed):
    """2. Test that stage restart atomically cleans up partial outputs and dq_results."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.FAILED
    
    st_silver = BatchStage(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_name=StageNameEnum.SILVER_RAW,
        stage_order=3,
        status=StageStatusEnum.FAILED,
        created_by="eng1",
        updated_by="eng1",
    )
    db.add(st_silver)
    db.flush()

    # Add prior dummy DQResult and QuarantineRecord
    from backend.models.rule import RuleVersion
    rule_ver = db.query(RuleVersion).first()
    dq = None
    if rule_ver:
        dq = DQResult(
            id=uuid.uuid4(),
            batch_id=batch.id,
            stage_id=st_silver.id,
            rule_version_id=rule_ver.id,
            total_rows_evaluated=10,
            passed_rows=8,
            failed_rows=2,
            pass_rate=80.0,
            action_taken=DQActionTakenEnum.LOGGED_WARNING,
            execution_duration_ms=12,
            created_by="eng1",
            updated_by="eng1",
        )
        db.add(dq)

    qr = QuarantineRecord(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_name=StageNameEnum.SILVER_RAW.value,
        source_row_number=1,
        source_record_raw="M001,John,Doe,1980-01-01,M",
        field_name="member_id",
        reason=QuarantineReasonEnum.INVALID_FIELD_TYPE,
        status=QuarantineStatusEnum.QUARANTINED,
        created_by="eng1",
        updated_by="eng1",
    )
    db.add(qr)
    db.flush()

    if dq:
        assert db.query(DQResult).filter(DQResult.batch_id == batch.id).count() == 1
    assert db.query(QuarantineRecord).filter(QuarantineRecord.batch_id == batch.id).count() == 1

    # Execute full pipeline first so Landing & Bronze exist
    executor = PipelineExecutor(db)
    executor.execute_batch(batch_id=batch.id, actor_id="eng1", simulate_failure_stage=StageNameEnum.SILVER_RAW)

    # Create a physical partial output file and link to st_silver
    storage = get_storage_adapter()
    partial_path = f"./data/silver_raw/test_partial_{uuid.uuid4().hex[:8]}.csv"
    storage.write_file(partial_path, b"partial,data,before,failure\n")
    st_silver.output_path = partial_path
    db.flush()
    assert storage.file_exists(partial_path) is True

    # Now call restart
    recovery_service = OpsRecoveryService(db)
    res_batch = recovery_service.restart_failed_batch(batch_id=batch.id, actor_id="eng1", reason="Restarting")
    assert res_batch.status == BatchStatusEnum.SUCCESS

    # Prior dummy dq result is gone
    if dq:
        assert db.query(DQResult).filter(DQResult.id == dq.id).count() == 0
    # Prior partial output file on disk was cleanly purged
    assert storage.file_exists(partial_path) is False


def test_restart_batch_conflict_on_running_batch(db, recovery_feed):
    """3. Test that attempting to restart a RUNNING batch raises 409 Conflict."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.RUNNING
    db.flush()

    recovery_service = OpsRecoveryService(db)
    with pytest.raises(HTTPException) as exc_info:
        recovery_service.restart_failed_batch(batch_id=batch.id, actor_id="eng1", reason="Conflict test")
    assert exc_info.value.status_code == 409


def test_restart_batch_rejected_on_success_without_retrigger(db, recovery_feed):
    """4. Test that attempting to restart an already SUCCESS batch raises 400 Bad Request."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.SUCCESS
    db.flush()

    recovery_service = OpsRecoveryService(db)
    with pytest.raises(HTTPException) as exc_info:
        recovery_service.restart_failed_batch(batch_id=batch.id, actor_id="eng1", reason="Should fail")
    assert exc_info.value.status_code == 400
    assert "RETRIGGER_BATCH" in exc_info.value.detail


def test_reprocess_quarantine_creates_recovery_batch(db, recovery_feed):
    """5. Test that reprocessing quarantine creates an isolated recovery batch."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    
    qr = QuarantineRecord(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_name=StageNameEnum.SILVER_RAW.value,
        source_row_number=1,
        source_record_raw="M001,Alice,Johnson,1985-06-15,F",
        field_name="member_id",
        reason=QuarantineReasonEnum.MISSING_REQUIRED_FIELD,
        status=QuarantineStatusEnum.QUARANTINED,
        created_by="eng1",
        updated_by="eng1",
    )
    db.add(qr)
    db.flush()

    recovery_service = OpsRecoveryService(db)
    summary = recovery_service.reprocess_quarantine_records(
        record_ids=[qr.id],
        actor_id="eng1",
        reason="Fixed mapping metadata",
    )

    assert "recovery_batch_id" in summary
    assert summary["total_evaluated"] == 1
    recovery_batch = db.query(Batch).filter(Batch.id == uuid.UUID(summary["recovery_batch_id"])).first()
    assert recovery_batch is not None
    assert recovery_batch.triggered_by == "quarantine_recovery"


def test_reprocess_quarantine_routes_valid_to_silver_and_updates_status(db, recovery_feed):
    """6. Test that valid records during quarantine reprocess update status to REPROCESSED with resolution_batch_id."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    
    # Valid record format for our recovery_feed
    qr = QuarantineRecord(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_name=StageNameEnum.SILVER_RAW.value,
        source_row_number=1,
        source_record_raw="M999,Carol,White,1992-04-10,F",
        field_name="date_of_birth",
        reason=QuarantineReasonEnum.INVALID_DATE_FORMAT,
        status=QuarantineStatusEnum.QUARANTINED,
        created_by="eng1",
        updated_by="eng1",
    )
    db.add(qr)
    db.flush()

    recovery_service = OpsRecoveryService(db)
    summary = recovery_service.reprocess_quarantine_records(
        record_ids=[qr.id],
        actor_id="eng1",
        reason="Manual reprocessing",
    )

    assert summary["reprocessed_count"] == 1
    assert summary["still_quarantined_count"] == 0

    db.refresh(qr)
    assert qr.status == QuarantineStatusEnum.REPROCESSED
    assert qr.resolution_batch_id == uuid.UUID(summary["recovery_batch_id"])
    assert qr.resolved_at is not None
    assert qr.resolved_by == "eng1"


def test_reprocess_quarantine_retains_still_invalid_records(db, recovery_feed):
    """7. Test that records still failing validation remain in QUARANTINED status."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    
    # Invalid record: missing required last_name
    qr = QuarantineRecord(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_name=StageNameEnum.SILVER_RAW.value,
        source_row_number=2,
        source_record_raw="M999,Carol,,1992-04-10,F",
        field_name="last_name",
        reason=QuarantineReasonEnum.MISSING_REQUIRED_FIELD,
        status=QuarantineStatusEnum.QUARANTINED,
        created_by="eng1",
        updated_by="eng1",
    )
    db.add(qr)
    db.flush()

    recovery_service = OpsRecoveryService(db)
    summary = recovery_service.reprocess_quarantine_records(
        record_ids=[qr.id],
        actor_id="eng1",
        reason="Attempt reprocessing",
    )

    assert summary["reprocessed_count"] == 0
    assert summary["still_quarantined_count"] == 1

    db.refresh(qr)
    assert qr.status == QuarantineStatusEnum.QUARANTINED
    assert qr.resolution_batch_id is None


def test_discard_quarantine_marks_records_discarded(db, recovery_feed):
    """8. Test that discarding quarantine records marks status to DISCARDED."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    
    qr = QuarantineRecord(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_name=StageNameEnum.SILVER_RAW.value,
        source_row_number=1,
        source_record_raw="BAD_DATA_GARBAGE",
        field_name="all",
        reason=QuarantineReasonEnum.ENCODING_ERROR,
        status=QuarantineStatusEnum.QUARANTINED,
        created_by="eng1",
        updated_by="eng1",
    )
    db.add(qr)
    db.flush()

    recovery_service = OpsRecoveryService(db)
    res = recovery_service.discard_quarantine_records(
        record_ids=[qr.id],
        actor_id="eng1",
        reason="Corrupt source record - partner confirmed unrecoverable",
    )

    assert res["discarded_count"] == 1
    db.refresh(qr)
    assert qr.status == QuarantineStatusEnum.DISCARDED
    assert qr.resolved_by == "eng1"
    assert "Corrupt source record" in qr.resolution_notes


def test_quarantine_reprocess_both_valid_and_invalid_end_to_end(db, recovery_feed):
    """Test reprocessing mixed records creates Silver Raw with lineage and keeps invalid quarantined."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)

    # Valid record: valid fields matching schema
    qr_valid = QuarantineRecord(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_name=StageNameEnum.SILVER_RAW.value,
        source_row_number=1,
        source_record_raw="M888,Jane,Goodall,1970-01-01,F",
        field_name="gender",
        reason=QuarantineReasonEnum.INVALID_ENUM_VALUE,
        status=QuarantineStatusEnum.QUARANTINED,
        created_by="system",
        updated_by="system",
    )
    # Invalid record: missing required first_name
    qr_invalid = QuarantineRecord(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_name=StageNameEnum.SILVER_RAW.value,
        source_row_number=2,
        source_record_raw="M889,,Smith,1980-01-01,F",
        field_name="first_name",
        reason=QuarantineReasonEnum.MISSING_REQUIRED_FIELD,
        status=QuarantineStatusEnum.QUARANTINED,
        created_by="system",
        updated_by="system",
    )
    db.add_all([qr_valid, qr_invalid])
    db.flush()

    recovery_service = OpsRecoveryService(db)
    summary = recovery_service.reprocess_quarantine_records(
        record_ids=[qr_valid.id, qr_invalid.id],
        actor_id="eng1",
        reason="Mixed quarantine batch reprocessing",
    )

    assert summary["reprocessed_count"] == 1
    assert summary["still_quarantined_count"] == 1
    assert summary["total_evaluated"] == 2

    # Check database records
    db.refresh(qr_valid)
    db.refresh(qr_invalid)

    assert qr_valid.status == QuarantineStatusEnum.REPROCESSED
    assert qr_valid.resolution_batch_id == uuid.UUID(summary["recovery_batch_id"])
    assert qr_valid.resolved_by == "eng1"

    assert qr_invalid.status == QuarantineStatusEnum.QUARANTINED
    assert qr_invalid.resolution_batch_id is None
    assert "Recovery attempt" in qr_invalid.resolution_notes
    assert "record remains invalid" in qr_invalid.resolution_notes

    # Check physical Silver Raw output file exists and has lineage headers
    storage = get_storage_adapter()
    file_path = f"./data/silver_raw/{feed.name}/{summary['recovery_batch_id']}/silver_raw_recovery.csv"
    assert storage.file_exists(file_path) is True
    file_content = storage.read_file(file_path).decode("utf-8")
    assert "_recovery_batch_id" in file_content
    assert "_quarantine_source_id" in file_content
    assert "_batch_id" in file_content
    assert "_feed_id" in file_content
    assert str(qr_valid.id) in file_content
    assert "Jane" in file_content


def test_quarantine_reprocess_idempotency_prevents_duplicate_silver_raw(db, recovery_feed):
    """Test calling reprocess on an already resolved record raises 400 and prevents duplicate output."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)

    qr = QuarantineRecord(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_name=StageNameEnum.SILVER_RAW.value,
        source_row_number=1,
        source_record_raw="M888,Jane,Goodall,1970-01-01,F",
        field_name="gender",
        reason=QuarantineReasonEnum.INVALID_ENUM_VALUE,
        status=QuarantineStatusEnum.REPROCESSED,
        resolution_batch_id=batch.id,
        created_by="system",
        updated_by="system",
    )
    db.add(qr)
    db.flush()

    recovery_service = OpsRecoveryService(db)
    with pytest.raises(HTTPException) as exc_info:
        recovery_service.reprocess_quarantine_records(
            record_ids=[qr.id],
            actor_id="eng1",
            reason="Duplicate reprocess attempt",
        )
    assert exc_info.value.status_code == 400
    assert "cannot be reprocessed" in exc_info.value.detail.lower()


def test_retrigger_successful_batch_links_parent_batch_id(db, recovery_feed):
    """Test retriggering successful batch creates child batch with parent_batch_id while original is unchanged."""
    feed, version = recovery_feed
    batch = _create_sample_batch(db, feed, version)
    batch.status = BatchStatusEnum.SUCCESS
    db.flush()

    recovery_service = OpsRecoveryService(db)
    new_batch = recovery_service.retrigger_successful_batch(
        batch_id=batch.id,
        actor_id="eng1",
        reason="Client retroactive reprocessing",
    )

    db.refresh(batch)
    assert batch.status == BatchStatusEnum.SUCCESS
    assert new_batch.id != batch.id
    assert new_batch.parent_batch_id == batch.id
    assert new_batch.triggered_by == "manual_retrigger"
    assert new_batch.status == BatchStatusEnum.SUCCESS

