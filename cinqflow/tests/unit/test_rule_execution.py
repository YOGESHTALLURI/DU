"""
Unit Tests for Data Quality Rule Execution against Sample Data — Wave 1 Slice 4
7 tests covering all 7 supported rule types: NOT_NULL, RANGE, REGEX, ENUM, LENGTH, DATE_RANGE, CROSS_FIELD.
Verifies both passing and failing row evaluations.
"""
import uuid
import pytest
from backend.models.feed import Feed, FeedFormatEnum
from backend.models.schema import Schema, SchemaVersion, SchemaField, SchemaVersionStatusEnum, SchemaDataTypeEnum, SampleFile
from backend.models.rule import RuleTypeEnum, RuleSeverityEnum
from backend.services.rule_service import RuleService
from backend.schemas.rule import RuleCreateRequest
from backend.adapters.storage import get_storage_adapter


@pytest.fixture
def test_feed_sample_and_rules(db):
    """Creates a feed with published schema and uploaded sample CSV containing mixed valid/invalid rows."""
    storage = get_storage_adapter()
    feed = Feed(
        id=uuid.uuid4(),
        name=f"Feed_Exec_{uuid.uuid4().hex[:6]}",
        domain="CLAIMS",
        format=FeedFormatEnum.CSV,
        landing_folder="claims/exec_test",
        filename_pattern="claims_*.csv",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(feed)
    db.flush()

    schema = Schema(
        id=uuid.uuid4(),
        feed_id=feed.id,
        name=f"{feed.name}_Schema",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(schema)
    db.flush()

    v1 = SchemaVersion(
        id=uuid.uuid4(),
        schema_id=schema.id,
        version_number=1,
        status=SchemaVersionStatusEnum.PUBLISHED,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(v1)
    db.flush()

    fields_v1 = [
        SchemaField(id=uuid.uuid4(), schema_version_id=v1.id, field_name="claim_id", data_type=SchemaDataTypeEnum.STRING, ordinal_position=1, created_by="engineer", updated_by="engineer"),
        SchemaField(id=uuid.uuid4(), schema_version_id=v1.id, field_name="amount", data_type=SchemaDataTypeEnum.DECIMAL, ordinal_position=2, created_by="engineer", updated_by="engineer"),
        SchemaField(id=uuid.uuid4(), schema_version_id=v1.id, field_name="paid_amount", data_type=SchemaDataTypeEnum.DECIMAL, ordinal_position=3, created_by="engineer", updated_by="engineer"),
        SchemaField(id=uuid.uuid4(), schema_version_id=v1.id, field_name="service_date", data_type=SchemaDataTypeEnum.DATE, ordinal_position=4, created_by="engineer", updated_by="engineer"),
        SchemaField(id=uuid.uuid4(), schema_version_id=v1.id, field_name="status", data_type=SchemaDataTypeEnum.STRING, ordinal_position=5, created_by="engineer", updated_by="engineer"),
        SchemaField(id=uuid.uuid4(), schema_version_id=v1.id, field_name="code", data_type=SchemaDataTypeEnum.STRING, ordinal_position=6, created_by="engineer", updated_by="engineer"),
    ]
    db.add_all(fields_v1)
    db.flush()

    # Create CSV sample with 4 rows:
    # Row 1: valid all
    # Row 2: claim_id null, amount out of range, code wrong regex, status invalid enum, len wrong, date wrong, cross-field fail
    # Row 3: mixed
    # Row 4: valid all
    csv_data = (
        "claim_id,amount,paid_amount,service_date,status,code\n"
        "CLM-101,150.00,120.00,2026-01-15,PAID,ABC-01\n"
        ",-50.00,200.00,2015-05-01,UNKNOWN,INVALID\n"
        "CLM-103,450.00,450.00,2026-02-10,DENIED,ABC-03\n"
        "CLM-104,75.25,50.00,2026-03-20,PENDING,ABC-04\n"
    ).encode("utf-8")

    storage_path = f"sample_files/{feed.id}/sample_claims.csv"
    storage.write_file(storage_path, csv_data)

    sample_file = SampleFile(
        id=uuid.uuid4(),
        feed_id=feed.id,
        filename="sample_claims.csv",
        storage_path=storage_path,
        file_size_bytes=len(csv_data),
        file_fingerprint="dummyfingerprint1234567890",
        mime_type="text/csv",
        row_count_estimate=4,
        uploaded_by="engineer",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(sample_file)
    db.commit()
    db.refresh(feed)
    db.refresh(sample_file)
    return feed, sample_file


# Test 16: NOT_NULL
def test_exec_not_null_pass_and_fail(db, test_feed_sample_and_rules):
    feed, sample = test_feed_sample_and_rules
    svc = RuleService(db)
    r = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="exec_not_null",
            target_field="claim_id",
            rule_type=RuleTypeEnum.NOT_NULL,
        ),
        actor_id="analyst",
    )
    res = svc.test_rule_version(r.id, r.draft_version.id, sample_id=sample.id, actor_id="analyst")
    assert res.total_rows == 4
    assert res.passed_rows == 3
    assert res.failed_rows == 1  # Row 2 is empty
    assert res.pass_rate == 75.0
    assert len(res.failed_row_details) == 1
    assert res.failed_row_details[0].row_number == 2


# Test 17: RANGE
def test_exec_range_pass_and_fail(db, test_feed_sample_and_rules):
    feed, sample = test_feed_sample_and_rules
    svc = RuleService(db)
    r = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="exec_range",
            target_field="amount",
            rule_type=RuleTypeEnum.RANGE,
            rule_config={"min": 0, "max": 500, "inclusive": True},
        ),
        actor_id="analyst",
    )
    res = svc.test_rule_version(r.id, r.draft_version.id, sample_id=sample.id, actor_id="analyst")
    assert res.total_rows == 4
    assert res.passed_rows == 3
    assert res.failed_rows == 1  # Row 2 has -50.00
    assert res.failed_row_details[0].row_number == 2


# Test 18: REGEX
def test_exec_regex_pass_and_fail(db, test_feed_sample_and_rules):
    feed, sample = test_feed_sample_and_rules
    svc = RuleService(db)
    r = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="exec_regex",
            target_field="code",
            rule_type=RuleTypeEnum.REGEX,
            rule_config={"pattern": r"^ABC-[0-9]{2}$"},
        ),
        actor_id="analyst",
    )
    res = svc.test_rule_version(r.id, r.draft_version.id, sample_id=sample.id, actor_id="analyst")
    assert res.total_rows == 4
    assert res.passed_rows == 3
    assert res.failed_rows == 1  # Row 2 is "INVALID"
    assert res.failed_row_details[0].row_number == 2


# Test 19: ENUM
def test_exec_enum_pass_and_fail(db, test_feed_sample_and_rules):
    feed, sample = test_feed_sample_and_rules
    svc = RuleService(db)
    r = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="exec_enum",
            target_field="status",
            rule_type=RuleTypeEnum.ENUM,
            rule_config={"allowed_values": ["PAID", "DENIED", "PENDING"], "case_sensitive": True},
        ),
        actor_id="analyst",
    )
    res = svc.test_rule_version(r.id, r.draft_version.id, sample_id=sample.id, actor_id="analyst")
    assert res.total_rows == 4
    assert res.passed_rows == 3
    assert res.failed_rows == 1  # Row 2 is "UNKNOWN"
    assert res.failed_row_details[0].row_number == 2


# Test 20: LENGTH
def test_exec_length_pass_and_fail(db, test_feed_sample_and_rules):
    feed, sample = test_feed_sample_and_rules
    svc = RuleService(db)
    r = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="exec_len",
            target_field="code",
            rule_type=RuleTypeEnum.LENGTH,
            rule_config={"min_length": 6, "max_length": 6},  # ABC-01 is 6 chars, INVALID is 7 chars
        ),
        actor_id="analyst",
    )
    res = svc.test_rule_version(r.id, r.draft_version.id, sample_id=sample.id, actor_id="analyst")
    assert res.total_rows == 4
    assert res.passed_rows == 3
    assert res.failed_rows == 1
    assert res.failed_row_details[0].row_number == 2


# Test 21: DATE_RANGE
def test_exec_date_range_pass_and_fail(db, test_feed_sample_and_rules):
    feed, sample = test_feed_sample_and_rules
    svc = RuleService(db)
    r = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="exec_date",
            target_field="service_date",
            rule_type=RuleTypeEnum.DATE_RANGE,
            rule_config={"min_date": "2026-01-01", "max_date": "2026-12-31", "format": "YYYY-MM-DD"},
        ),
        actor_id="analyst",
    )
    res = svc.test_rule_version(r.id, r.draft_version.id, sample_id=sample.id, actor_id="analyst")
    assert res.total_rows == 4
    assert res.passed_rows == 3
    assert res.failed_rows == 1  # Row 2 is 2015-05-01
    assert res.failed_row_details[0].row_number == 2


# Test 22: CROSS_FIELD
def test_exec_cross_field_pass_and_fail(db, test_feed_sample_and_rules):
    feed, sample = test_feed_sample_and_rules
    svc = RuleService(db)
    r = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="exec_cross",
            target_field="amount",
            rule_type=RuleTypeEnum.CROSS_FIELD,
            rule_config={"compare_field": "paid_amount", "operator": "GTE"},  # amount >= paid_amount
        ),
        actor_id="analyst",
    )
    res = svc.test_rule_version(r.id, r.draft_version.id, sample_id=sample.id, actor_id="analyst")
    # Row 1: 150 >= 120 (pass)
    # Row 2: -50 >= 200 (fail)
    # Row 3: 450 >= 450 (pass)
    # Row 4: 75.25 >= 50 (pass)
    assert res.total_rows == 4
    assert res.passed_rows == 3
    assert res.failed_rows == 1
    assert res.failed_row_details[0].row_number == 2
