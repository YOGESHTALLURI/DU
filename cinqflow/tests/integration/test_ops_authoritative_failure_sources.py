"""
Integration tests for All 4 Authoritative Pipeline Failure Sources
Wave 2 Slice 4 Blocker 3

Verifies live end-to-end alert generation from real PipelineExecutor runs:
1. Breaking Schema Drift -> FailureCategoryEnum.SCHEMA_DRIFT alert in LANDING
2. Production DQ Abort -> FailureCategoryEnum.DATA_QUALITY alert in SILVER_RAW
3. Stage Execution Error -> FailureCategoryEnum.STAGE_EXECUTION alert
4. Reconciliation Failure -> FailureCategoryEnum.RECONCILIATION alert
"""
import uuid
import hashlib
import pytest
from datetime import datetime, timezone

from backend.models.feed import Feed, FeedFormatEnum, FeedStatusEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.pipeline import Batch, BatchStatusEnum, StageNameEnum
from backend.models.input_registry import InputRegistry, InputStatusEnum
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
from backend.models.incident import (
    OperationalAlert,
    FailureCategoryEnum,
    AlertStatusEnum,
    AlertSeverityEnum,
)
from backend.engine.executor import PipelineExecutor
from backend.adapters.storage import get_storage_adapter


@pytest.fixture
def base_feed_setup(db):
    prefix = uuid.uuid4().hex[:6]
    storage = get_storage_adapter()

    feed = Feed(
        id=uuid.uuid4(),
        name=f"FAIL_SRC_FEED_{prefix}",
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
        name=f"Schema_{prefix}",
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

    fields = [
        SchemaField(
            id=uuid.uuid4(),
            schema_version_id=sv.id,
            field_name="member_id",
            ordinal_position=1,
            data_type=SchemaDataTypeEnum.STRING,
            is_required=True,
            created_by="engineer",
            updated_by="engineer",
        ),
        SchemaField(
            id=uuid.uuid4(),
            schema_version_id=sv.id,
            field_name="first_name",
            ordinal_position=2,
            data_type=SchemaDataTypeEnum.STRING,
            is_required=True,
            created_by="engineer",
            updated_by="engineer",
        ),
        SchemaField(
            id=uuid.uuid4(),
            schema_version_id=sv.id,
            field_name="dob",
            ordinal_position=3,
            data_type=SchemaDataTypeEnum.DATE,
            is_required=True,
            created_by="engineer",
            updated_by="engineer",
        ),
    ]
    for f in fields:
        db.add(f)
    db.commit()

    return {
        "feed": feed,
        "feed_version": fv,
        "schema_version": sv,
        "storage": storage,
    }


def test_failure_source_1_breaking_schema_drift(db, base_feed_setup):
    """Source 1: File with missing required column triggers breaking drift -> OperationalAlert (SCHEMA_DRIFT)."""
    feed = base_feed_setup["feed"]
    fv = base_feed_setup["feed_version"]
    storage = base_feed_setup["storage"]

    # File is missing 'dob' required field
    content = b"member_id,first_name\nM001,Alice\nM002,Bob\n"
    file_path = f"./data/landing/{feed.id}/drift_input.csv"
    storage.write_file(file_path, content)
    fingerprint = hashlib.sha256(content).hexdigest()

    input_reg = InputRegistry(
        id=uuid.uuid4(),
        feed_id=feed.id,
        filename="drift_input.csv",
        file_path=file_path,
        file_size_bytes=len(content),
        file_fingerprint=fingerprint,
        status=InputStatusEnum.ACCEPTED,
        registered_by="test",
        detected_at=datetime.now(timezone.utc),
        created_by="test",
        updated_by="test",
    )
    db.add(input_reg)
    db.flush()

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        input_registry_id=input_reg.id,
        status=BatchStatusEnum.PENDING,
        triggered_by="test",
        created_by="test",
        updated_by="test",
    )
    db.add(batch)
    db.commit()

    executor = PipelineExecutor(db)
    res_batch = executor.execute_batch(batch_id=batch.id, actor_id="test")

    assert res_batch.status == BatchStatusEnum.FAILED

    # Verify Alert was created
    alert = (
        db.query(OperationalAlert)
        .filter(OperationalAlert.batch_id == batch.id)
        .first()
    )
    assert alert is not None
    assert alert.status == AlertStatusEnum.OPEN
    assert alert.fingerprint.category == FailureCategoryEnum.SCHEMA_DRIFT
    assert alert.fingerprint.failure_stage == "LANDING"
    assert "schema drift" in alert.title.lower() or "schema drift" in alert.description.lower()


def test_failure_source_2_production_dq_abort(db, base_feed_setup):
    """Source 2: File violating REJECT_FILE rule aborts batch -> OperationalAlert (DATA_QUALITY)."""
    feed = base_feed_setup["feed"]
    fv = base_feed_setup["feed_version"]
    sv = base_feed_setup["schema_version"]
    storage = base_feed_setup["storage"]

    # Add a REJECT_FILE rule on first_name NOT_NULL
    rule = DataQualityRule(
        id=uuid.uuid4(),
        feed_id=feed.id,
        schema_id=sv.schema_id,
        name=f"Rule_Reject_Null_First_{uuid.uuid4().hex[:6]}",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(rule)
    db.flush()

    rv = RuleVersion(
        id=uuid.uuid4(),
        rule_id=rule.id,
        version_number=1,
        schema_version_id=sv.id,
        rule_type=RuleTypeEnum.NOT_NULL,
        target_field="first_name",
        rule_config={},
        severity=RuleSeverityEnum.REJECT_FILE,
        status=RuleVersionStatusEnum.PUBLISHED,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(rv)
    db.commit()

    # Ingest file where second row has empty first_name
    content = b"member_id,first_name,dob\nM001,Alice,1990-01-01\nM002,,1992-05-15\n"
    file_path = f"./data/landing/{feed.id}/dq_abort_input.csv"
    storage.write_file(file_path, content)
    fingerprint = hashlib.sha256(content).hexdigest()

    input_reg = InputRegistry(
        id=uuid.uuid4(),
        feed_id=feed.id,
        filename="dq_abort_input.csv",
        file_path=file_path,
        file_size_bytes=len(content),
        file_fingerprint=fingerprint,
        status=InputStatusEnum.ACCEPTED,
        registered_by="test",
        detected_at=datetime.now(timezone.utc),
        created_by="test",
        updated_by="test",
    )
    db.add(input_reg)
    db.flush()

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        input_registry_id=input_reg.id,
        status=BatchStatusEnum.PENDING,
        triggered_by="test",
        created_by="test",
        updated_by="test",
    )
    db.add(batch)
    db.commit()

    executor = PipelineExecutor(db)
    res_batch = executor.execute_batch(batch_id=batch.id, actor_id="test")

    assert res_batch.status == BatchStatusEnum.FAILED

    alert = (
        db.query(OperationalAlert)
        .filter(OperationalAlert.batch_id == batch.id)
        .first()
    )
    assert alert is not None
    assert alert.status == AlertStatusEnum.OPEN
    assert alert.fingerprint.category == FailureCategoryEnum.DATA_QUALITY
    assert alert.fingerprint.failure_stage == "SILVER_RAW"
    assert "data quality" in alert.title.lower() or "data quality" in alert.description.lower()


def test_failure_source_3_stage_execution_error(db, base_feed_setup):
    """Source 3: Stage execution error -> OperationalAlert (STAGE_EXECUTION)."""
    feed = base_feed_setup["feed"]
    fv = base_feed_setup["feed_version"]
    storage = base_feed_setup["storage"]

    content = b"member_id,first_name,dob\nM001,Alice,1990-01-01\n"
    file_path = f"./data/landing/{feed.id}/stage_err_input.csv"
    storage.write_file(file_path, content)
    fingerprint = hashlib.sha256(content).hexdigest()

    input_reg = InputRegistry(
        id=uuid.uuid4(),
        feed_id=feed.id,
        filename="stage_err_input.csv",
        file_path=file_path,
        file_size_bytes=len(content),
        file_fingerprint=fingerprint,
        status=InputStatusEnum.ACCEPTED,
        registered_by="test",
        detected_at=datetime.now(timezone.utc),
        created_by="test",
        updated_by="test",
    )
    db.add(input_reg)
    db.flush()

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        input_registry_id=input_reg.id,
        status=BatchStatusEnum.PENDING,
        triggered_by="test",
        created_by="test",
        updated_by="test",
    )
    db.add(batch)
    db.commit()

    executor = PipelineExecutor(db)
    # Simulate execution failure at Bronze stage
    res_batch = executor.execute_batch(
        batch_id=batch.id,
        actor_id="test",
        simulate_failure_stage=StageNameEnum.BRONZE,
    )

    assert res_batch.status == BatchStatusEnum.FAILED

    alert = (
        db.query(OperationalAlert)
        .filter(OperationalAlert.batch_id == batch.id)
        .first()
    )
    assert alert is not None
    assert alert.fingerprint.category == FailureCategoryEnum.STAGE_EXECUTION
    assert alert.fingerprint.failure_stage == "BRONZE"


def test_failure_source_4_reconciliation_failure(db, base_feed_setup):
    """Source 4: Reconciliation record imbalance -> OperationalAlert (RECONCILIATION)."""
    feed = base_feed_setup["feed"]
    fv = base_feed_setup["feed_version"]

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        status=BatchStatusEnum.RUNNING,
        triggered_by="test",
        created_by="test",
        updated_by="test",
    )
    db.add(batch)
    db.flush()

    # Directly invoke compute_reconciliation with intentional imbalance (rows_in != rows_silver + rows_quarantine)
    executor = PipelineExecutor(db)
    imbalanced_context = {
        "total_rows": 100,
        "valid_rows_count": 80,  # 80 + 10 = 90 != 100 (discrepancy = 10 rows lost)
        "quarantined_count": 10,
        "quarantine_reasons": {"INVALID_FORMAT": 10},
    }

    executor._compute_reconciliation(
        batch=batch,
        context=imbalanced_context,
        actor_id="test-recon",
        actor_email="recon@test.com",
    )
    db.commit()

    assert batch.status == BatchStatusEnum.FAILED_RECONCILIATION

    alert = (
        db.query(OperationalAlert)
        .filter(OperationalAlert.batch_id == batch.id)
        .first()
    )
    assert alert is not None
    assert alert.fingerprint.category == FailureCategoryEnum.RECONCILIATION
    assert alert.fingerprint.failure_stage == "RECONCILIATION"
    assert "reconciliation" in alert.title.lower() or "balance" in alert.title.lower()
