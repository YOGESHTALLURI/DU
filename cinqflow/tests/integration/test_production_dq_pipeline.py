"""
Integration Tests for Production DQ & Schema Drift Ingestion Pipeline — Wave 2 Slice 1
(CF-V2-E5-04 and CF-V2-E7-05)
"""
import io
import uuid
import pytest
from datetime import datetime, timezone
from fastapi import HTTPException

from backend.models.feed import Feed, FeedFormatEnum, FeedStatusEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStage, BatchStatusEnum, StageNameEnum, StageStatusEnum
from backend.models.input_registry import InputRegistry, QuarantineRecord
from backend.models.reconciliation import BatchReconciliation
from backend.models.schema import (
    Schema,
    SchemaVersion,
    SchemaField,
    SchemaDataTypeEnum,
    SchemaVersionStatusEnum,
)
from backend.models.rule import (
    DataQualityRule,
    RuleVersion,
    RuleVersionStatusEnum,
    RuleTypeEnum,
    RuleSeverityEnum,
)
from backend.models.drift import SchemaDriftReport, DriftSeverityEnum
from backend.models.dq_result import DQResult, DQActionTakenEnum
from backend.engine.executor import PipelineExecutor
from backend.adapters.storage import get_storage_adapter


@pytest.fixture
def test_feed_setup(db):
    """Sets up a complete Feed with published SchemaVersion and initial input file."""
    prefix = uuid.uuid4().hex[:6]
    storage = get_storage_adapter()

    feed = Feed(
        id=uuid.uuid4(),
        name=f"PROD_FEED_{prefix}",
        domain="MEMBERS",
        format=FeedFormatEnum.CSV,
        status=FeedStatusEnum.ACTIVE,
        landing_folder=f"./data/landing/{prefix}",
        filename_pattern="*.csv",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(feed)
    db.flush()

    fv = FeedVersion(
        id=uuid.uuid4(),
        feed_id=feed.id,
        version_number=1,
        status=FeedVersionStatusEnum.PUBLISHED,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(fv)
    db.flush()

    schema_obj = Schema(
        id=uuid.uuid4(),
        feed_id=feed.id,
        name=f"Schema for {feed.name}",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(schema_obj)
    db.flush()

    sv = SchemaVersion(
        id=uuid.uuid4(),
        schema_id=schema_obj.id,
        version_number=1,
        status=SchemaVersionStatusEnum.PUBLISHED,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(sv)
    db.flush()

    # Define fields: member_id (req), first_name (req), age (opt)
    f_mid = SchemaField(
        id=uuid.uuid4(),
        schema_version_id=sv.id,
        field_name="member_id",
        data_type=SchemaDataTypeEnum.STRING,
        is_required=True,
        ordinal_position=1,
        created_by="engineer",
        updated_by="engineer",
    )
    f_fname = SchemaField(
        id=uuid.uuid4(),
        schema_version_id=sv.id,
        field_name="first_name",
        data_type=SchemaDataTypeEnum.STRING,
        is_required=True,
        ordinal_position=2,
        created_by="engineer",
        updated_by="engineer",
    )
    f_age = SchemaField(
        id=uuid.uuid4(),
        schema_version_id=sv.id,
        field_name="age",
        data_type=SchemaDataTypeEnum.INTEGER,
        is_required=False,
        ordinal_position=3,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add_all([f_mid, f_fname, f_age])
    db.commit()

    return {
        "feed": feed,
        "feed_version": fv,
        "schema": schema_obj,
        "schema_version": sv,
        "storage": storage,
    }


def _create_batch_with_csv(db, setup, csv_content: bytes, filename="test_input.csv") -> Batch:
    feed = setup["feed"]
    fv = setup["feed_version"]
    storage = setup["storage"]

    import hashlib
    fp = hashlib.sha256(csv_content).hexdigest()
    file_path = f"./data/landing/{feed.id}/{filename}"
    storage.write_file(file_path, csv_content)

    input_reg = InputRegistry(
        id=uuid.uuid4(),
        feed_id=feed.id,
        filename=filename,
        file_path=file_path,
        file_size_bytes=len(csv_content),
        file_fingerprint=fp,
        registered_by="engineer",
        detected_at=datetime.now(timezone.utc),
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(input_reg)
    db.flush()

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        input_registry_id=input_reg.id,
        status=BatchStatusEnum.PENDING,
        triggered_by="engineer",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


def test_pipeline_breaking_drift_halts_landing_stage(db, test_feed_setup):
    """CSV missing required 'first_name' column halts batch at LANDING stage."""
    # CSV has member_id, age -> missing required 'first_name'
    csv_bytes = b"member_id,age\nM101,30\nM102,45\n"
    batch = _create_batch_with_csv(db, test_feed_setup, csv_bytes, "breaking_drift.csv")

    executor = PipelineExecutor(db)
    batch_res = executor.execute_batch(batch_id=batch.id, actor_id="engineer")

    assert batch_res.status == BatchStatusEnum.FAILED
    assert "breaking schema drift" in batch_res.error_message.lower()

    # Stage LANDING must be FAILED; BRONZE and SILVER_RAW must not be run
    s_landing = batch_res.get_stage(StageNameEnum.LANDING)
    assert s_landing.status == StageStatusEnum.FAILED

    s_bronze = batch_res.get_stage(StageNameEnum.BRONZE)
    assert s_bronze is None or s_bronze.status == StageStatusEnum.PENDING

    # Verify drift report recorded
    drift = db.query(SchemaDriftReport).filter(SchemaDriftReport.batch_id == batch.id).first()
    assert drift is not None
    assert drift.drift_severity == DriftSeverityEnum.BREAKING
    assert "first_name" in drift.missing_fields


def test_pipeline_non_breaking_drift_allows_batch_success(db, test_feed_setup):
    """CSV with unexpected extra column records report but completes batch."""
    # CSV has member_id, first_name, and unexpected extra 'phone_num'
    csv_bytes = b"member_id,first_name,phone_num\nM101,Alice,555-0101\nM102,Bob,555-0102\n"
    batch = _create_batch_with_csv(db, test_feed_setup, csv_bytes, "non_breaking.csv")

    executor = PipelineExecutor(db)
    batch_res = executor.execute_batch(batch_id=batch.id, actor_id="engineer")

    assert batch_res.status == BatchStatusEnum.SUCCESS

    # Verify drift report exists as NON_BREAKING
    drift = db.query(SchemaDriftReport).filter(SchemaDriftReport.batch_id == batch.id).first()
    assert drift is not None
    assert drift.drift_severity == DriftSeverityEnum.NON_BREAKING
    assert "phone_num" in drift.unexpected_fields


def test_pipeline_executes_only_published_pinned_rules(db, test_feed_setup):
    """Rules in DRAFT or pinned to another schema version are ignored during production execution."""
    feed = test_feed_setup["feed"]
    sv = test_feed_setup["schema_version"]

    rule = DataQualityRule(
        id=uuid.uuid4(),
        feed_id=feed.id,
        schema_id=test_feed_setup["schema"].id,
        name="draft_rule_ignored",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(rule)
    db.flush()

    # Draft rule version
    r_draft = RuleVersion(
        id=uuid.uuid4(),
        rule_id=rule.id,
        version_number=1,
        schema_version_id=sv.id,
        status=RuleVersionStatusEnum.DRAFT,
        rule_type=RuleTypeEnum.NOT_NULL,
        target_field="member_id",
        severity=RuleSeverityEnum.QUARANTINE,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(r_draft)
    db.commit()

    csv_bytes = b"member_id,first_name\n,Alice\nM102,Bob\n"
    batch = _create_batch_with_csv(db, test_feed_setup, csv_bytes, "draft_rule_test.csv")

    executor = PipelineExecutor(db)
    batch_res = executor.execute_batch(batch_id=batch.id, actor_id="engineer")

    # Draft rule was not published, so dq_results for it must be 0
    dq_res = db.query(DQResult).filter(DQResult.batch_id == batch.id, DQResult.rule_version_id == r_draft.id).first()
    assert dq_res is None


def test_pipeline_info_and_warning_severities_do_not_quarantine(db, test_feed_setup):
    """Rules with INFO or WARNING severities record failures in dq_results but pass rows forward."""
    feed = test_feed_setup["feed"]
    sv = test_feed_setup["schema_version"]

    rule = DataQualityRule(
        id=uuid.uuid4(),
        feed_id=feed.id,
        schema_id=test_feed_setup["schema"].id,
        name="age_warning_rule",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(rule)
    db.flush()

    r_pub = RuleVersion(
        id=uuid.uuid4(),
        rule_id=rule.id,
        version_number=1,
        schema_version_id=sv.id,
        status=RuleVersionStatusEnum.PUBLISHED,
        rule_type=RuleTypeEnum.RANGE,
        target_field="age",
        severity=RuleSeverityEnum.WARNING,
        rule_config={"min": 18, "max": 65},
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(r_pub)
    db.commit()

    # Row 1 age 70 fails warning; Row 2 age 25 passes
    csv_bytes = b"member_id,first_name,age\nM101,Alice,70\nM102,Bob,25\n"
    batch = _create_batch_with_csv(db, test_feed_setup, csv_bytes, "warning_rule_test.csv")

    executor = PipelineExecutor(db)
    batch_res = executor.execute_batch(batch_id=batch.id, actor_id="engineer")

    assert batch_res.status == BatchStatusEnum.SUCCESS

    # dq_results has 1 failure, action LOGGED_WARNING
    dq_res = db.query(DQResult).filter(DQResult.batch_id == batch.id, DQResult.rule_version_id == r_pub.id).first()
    assert dq_res is not None
    assert dq_res.failed_rows == 1
    assert dq_res.passed_rows == 1
    assert dq_res.action_taken == DQActionTakenEnum.LOGGED_WARNING

    # Zero rows quarantined from warning rule
    quarantined = db.query(QuarantineRecord).filter(QuarantineRecord.batch_id == batch.id).count()
    assert quarantined == 0


def test_pipeline_quarantine_severity_routes_to_quarantine_records(db, test_feed_setup):
    """QUARANTINE rule drops failing row, creates QuarantineRecord, and decrements rows_out."""
    feed = test_feed_setup["feed"]
    sv = test_feed_setup["schema_version"]

    rule = DataQualityRule(
        id=uuid.uuid4(),
        feed_id=feed.id,
        schema_id=test_feed_setup["schema"].id,
        name="member_id_format_regex",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(rule)
    db.flush()

    r_pub = RuleVersion(
        id=uuid.uuid4(),
        rule_id=rule.id,
        version_number=1,
        schema_version_id=sv.id,
        status=RuleVersionStatusEnum.PUBLISHED,
        rule_type=RuleTypeEnum.REGEX,
        target_field="member_id",
        severity=RuleSeverityEnum.QUARANTINE,
        rule_config={"pattern": r"^M\d{3}$"},  # M followed by 3 digits
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(r_pub)
    db.commit()

    # Row 1 (M101) valid; Row 2 (BADID) invalid
    csv_bytes = b"member_id,first_name,age\nM101,Alice,30\nBADID,Bob,25\n"
    batch = _create_batch_with_csv(db, test_feed_setup, csv_bytes, "quarantine_test.csv")

    executor = PipelineExecutor(db)
    batch_res = executor.execute_batch(batch_id=batch.id, actor_id="engineer")

    assert batch_res.status == BatchStatusEnum.SUCCESS

    # Check quarantine record created
    qr = db.query(QuarantineRecord).filter(QuarantineRecord.batch_id == batch.id).first()
    assert qr is not None
    assert qr.source_row_number == 2
    assert "BADID" in qr.source_record_raw

    # Check dq_results
    dq_res = db.query(DQResult).filter(DQResult.batch_id == batch.id, DQResult.rule_version_id == r_pub.id).first()
    assert dq_res is not None
    assert dq_res.failed_rows == 1
    assert dq_res.passed_rows == 1
    assert dq_res.action_taken == DQActionTakenEnum.QUARANTINED_ROWS


def test_pipeline_reject_file_severity_aborts_batch(db, test_feed_setup):
    """REJECT_FILE rule violation immediately aborts SILVER_RAW and marks batch FAILED."""
    feed = test_feed_setup["feed"]
    sv = test_feed_setup["schema_version"]

    rule = DataQualityRule(
        id=uuid.uuid4(),
        feed_id=feed.id,
        schema_id=test_feed_setup["schema"].id,
        name="member_id_must_be_present_critical",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(rule)
    db.flush()

    r_pub = RuleVersion(
        id=uuid.uuid4(),
        rule_id=rule.id,
        version_number=1,
        schema_version_id=sv.id,
        status=RuleVersionStatusEnum.PUBLISHED,
        rule_type=RuleTypeEnum.NOT_NULL,
        target_field="member_id",
        severity=RuleSeverityEnum.REJECT_FILE,
        rule_config={},
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(r_pub)
    db.commit()

    # First row has empty member_id
    csv_bytes = b"member_id,first_name,age\n,Alice,30\nM102,Bob,25\n"
    batch = _create_batch_with_csv(db, test_feed_setup, csv_bytes, "reject_file_test.csv")

    executor = PipelineExecutor(db)
    batch_res = executor.execute_batch(batch_id=batch.id, actor_id="engineer")

    assert batch_res.status == BatchStatusEnum.FAILED
    assert "rejected by rule" in batch_res.error_message.lower()

    # dq_results has action BATCH_ABORTED
    dq_res = db.query(DQResult).filter(DQResult.batch_id == batch.id, DQResult.rule_version_id == r_pub.id).first()
    assert dq_res is not None
    assert dq_res.action_taken == DQActionTakenEnum.BATCH_ABORTED


def test_pipeline_reconciliation_exact_balance_with_dq_quarantine(db, test_feed_setup):
    """Reconciliation verifies exact equality: rows_in = rows_out + rows_quarantined."""
    feed = test_feed_setup["feed"]
    sv = test_feed_setup["schema_version"]

    rule = DataQualityRule(
        id=uuid.uuid4(),
        feed_id=feed.id,
        schema_id=test_feed_setup["schema"].id,
        name="age_cap_rule",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(rule)
    db.flush()

    r_pub = RuleVersion(
        id=uuid.uuid4(),
        rule_id=rule.id,
        version_number=1,
        schema_version_id=sv.id,
        status=RuleVersionStatusEnum.PUBLISHED,
        rule_type=RuleTypeEnum.RANGE,
        target_field="age",
        severity=RuleSeverityEnum.QUARANTINE,
        rule_config={"max": 50},
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(r_pub)
    db.commit()

    # 4 rows: 2 valid (age <= 50), 2 quarantined (age > 50)
    csv_bytes = b"member_id,first_name,age\nM101,A,25\nM102,B,60\nM103,C,30\nM104,D,80\n"
    batch = _create_batch_with_csv(db, test_feed_setup, csv_bytes, "recon_balance_test.csv")

    executor = PipelineExecutor(db)
    batch_res = executor.execute_batch(batch_id=batch.id, actor_id="engineer")

    assert batch_res.status == BatchStatusEnum.SUCCESS

    # Check reconciliation table
    recon = db.query(BatchReconciliation).filter(BatchReconciliation.batch_id == batch.id).first()
    assert recon is not None
    assert recon.rows_in == 4
    assert recon.rows_silver_raw == 2
    assert recon.rows_quarantined == 2
    assert recon.balance_check_passed is True


def test_pipeline_idempotent_rerun_replaces_prior_dq_results(db, test_feed_setup):
    """Re-executing a stage purges previous dq_results without duplicate row errors."""
    feed = test_feed_setup["feed"]
    sv = test_feed_setup["schema_version"]

    rule = DataQualityRule(
        id=uuid.uuid4(),
        feed_id=feed.id,
        schema_id=test_feed_setup["schema"].id,
        name="idempotent_rule_test",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(rule)
    db.flush()

    r_pub = RuleVersion(
        id=uuid.uuid4(),
        rule_id=rule.id,
        version_number=1,
        schema_version_id=sv.id,
        status=RuleVersionStatusEnum.PUBLISHED,
        rule_type=RuleTypeEnum.NOT_NULL,
        target_field="first_name",
        severity=RuleSeverityEnum.INFO,
        rule_config={},
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(r_pub)
    db.commit()

    csv_bytes = b"member_id,first_name,age\nM101,Alice,30\n"
    batch = _create_batch_with_csv(db, test_feed_setup, csv_bytes, "idempotency_test.csv")

    executor = PipelineExecutor(db)
    batch_res = executor.execute_batch(batch_id=batch.id, actor_id="engineer")
    assert batch_res.status == BatchStatusEnum.SUCCESS

    # Manually reset Silver Raw to PENDING and batch to PENDING to simulate restart
    s_silver = batch.get_stage(StageNameEnum.SILVER_RAW)
    s_silver.status = StageStatusEnum.PENDING
    batch.status = BatchStatusEnum.PENDING
    db.commit()

    # Re-run
    batch_res_2 = executor.execute_batch(batch_id=batch.id, actor_id="engineer")
    assert batch_res_2.status == BatchStatusEnum.SUCCESS

    # Exactly 1 entry in dq_results (no duplicates)
    count = db.query(DQResult).filter(DQResult.batch_id == batch.id, DQResult.rule_version_id == r_pub.id).count()
    assert count == 1


def test_pipeline_concurrency_pessimistic_lock_blocks_simultaneous_run(db, test_feed_setup):
    """Attempting to execute an already RUNNING batch raises HTTP 409 Conflict."""
    csv_bytes = b"member_id,first_name,age\nM101,Alice,30\n"
    batch = _create_batch_with_csv(db, test_feed_setup, csv_bytes, "concurrency_test.csv")

    # Set batch status to RUNNING
    batch.status = BatchStatusEnum.RUNNING
    db.commit()

    executor = PipelineExecutor(db)
    with pytest.raises(HTTPException) as exc_info:
        executor.execute_batch(batch_id=batch.id, actor_id="engineer")

    assert exc_info.value.status_code == 409
    assert "already RUNNING" in exc_info.value.detail
