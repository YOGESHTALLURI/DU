"""
Integration Tests for Data Quality Rule Governance — Wave 1 Slice 4
4 tests covering:
1. test_rule_rbac_read_only_forbidden (403 on all mutations, 200 on read/validate)
2. test_rule_audit_all_six_events (all 6 audit events logged with zero sample values)
3. test_step4_published_rule_valid_with_newer_draft (Step 4 governance precision)
4. test_rule_test_results_zero_sample_values_persisted (DB level check of zero data leakage)
"""
import uuid
import pytest
from backend.models.feed import Feed, FeedFormatEnum, FeedStatusEnum
from backend.models.schema import (
    Schema,
    SchemaVersion,
    SchemaField,
    SchemaVersionStatusEnum,
    SchemaDataTypeEnum,
    SampleFile,
    ProfilingRun,
    ProfilingRunStatusEnum,
    OnboardingSession,
    OnboardingStatusEnum,
)
from backend.models.canonical_model import CanonicalModel, CanonicalField
from backend.models.mapping import Mapping, MappingVersion, MappingLine, MappingVersionStatusEnum, TransformTypeEnum
from backend.models.rule import DataQualityRule, RuleVersion, RuleTestRun, RuleVersionStatusEnum, RuleTypeEnum, RuleSeverityEnum
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.adapters.storage import get_storage_adapter


@pytest.fixture
def setup_governance_data(db):
    storage = get_storage_adapter()
    feed = Feed(
        id=uuid.uuid4(),
        name=f"Feed_Gov_{uuid.uuid4().hex[:6]}",
        domain="CLAIMS",
        format=FeedFormatEnum.CSV,
        landing_folder="claims/gov",
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

    schema_v1 = SchemaVersion(
        id=uuid.uuid4(),
        schema_id=schema.id,
        version_number=1,
        status=SchemaVersionStatusEnum.PUBLISHED,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(schema_v1)
    db.flush()

    f1 = SchemaField(id=uuid.uuid4(), schema_version_id=schema_v1.id, field_name="claim_id", data_type=SchemaDataTypeEnum.STRING, ordinal_position=1, created_by="engineer", updated_by="engineer")
    f2 = SchemaField(id=uuid.uuid4(), schema_version_id=schema_v1.id, field_name="amount", data_type=SchemaDataTypeEnum.DECIMAL, ordinal_position=2, created_by="engineer", updated_by="engineer")
    db.add_all([f1, f2])
    db.flush()

    csv_data = b"claim_id,amount\nCLM-01,100\nCLM-02,200\n"
    storage_path = f"sample_files/{feed.id}/sample.csv"
    storage.write_file(storage_path, csv_data)

    sample = SampleFile(
        id=uuid.uuid4(),
        feed_id=feed.id,
        filename="sample.csv",
        storage_path=storage_path,
        file_size_bytes=len(csv_data),
        file_fingerprint="fpgov1234567890",
        mime_type="text/csv",
        row_count_estimate=2,
        uploaded_by="engineer",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(sample)
    db.flush()

    p_run = ProfilingRun(
        id=uuid.uuid4(),
        feed_id=feed.id,
        sample_file_id=sample.id,
        status=ProfilingRunStatusEnum.COMPLETED,
        row_count=2,
        column_count=2,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(p_run)
    db.flush()

    # Canonical model + published mapping
    c_model = CanonicalModel(
        id=uuid.uuid4(),
        name=f"GovClaim_{uuid.uuid4().hex[:4]}",
        domain="CLAIMS",
        description="Gov claim",
        created_by="system",
        updated_by="system",
    )
    db.add(c_model)
    db.flush()

    c_field = CanonicalField(
        id=uuid.uuid4(),
        canonical_model_id=c_model.id,
        field_name="claim_num",
        data_type="STRING",
        is_required=True,
        ordinal_position=1,
        created_by="system",
        updated_by="system",
    )
    db.add(c_field)
    db.flush()

    mapping = Mapping(
        id=uuid.uuid4(),
        feed_id=feed.id,
        schema_id=schema.id,
        canonical_model_id=c_model.id,
        name=f"{feed.name}_to_{c_model.name}",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(mapping)
    db.flush()

    map_v1 = MappingVersion(
        id=uuid.uuid4(),
        mapping_id=mapping.id,
        version_number=1,
        schema_version_id=schema_v1.id,
        status=MappingVersionStatusEnum.PUBLISHED,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(map_v1)
    db.flush()

    m_line = MappingLine(
        id=uuid.uuid4(),
        mapping_version_id=map_v1.id,
        canonical_field_id=c_field.id,
        source_field_names=["claim_id"],
        transform_type=TransformTypeEnum.DIRECT,
        transform_params={},
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(m_line)
    db.flush()

    session = OnboardingSession(
        id=uuid.uuid4(),
        feed_id=feed.id,
        current_step=4,
        completed_steps=[1, 2, 3],
        sample_file_id=sample.id,
        profiling_run_id=p_run.id,
        schema_id=schema.id,
        status=OnboardingStatusEnum.IN_PROGRESS,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(session)
    db.commit()
    return feed, schema, schema_v1, sample, session


# Test 26
def test_rule_rbac_read_only_forbidden(client, readonly_token, engineer_token, setup_governance_data):
    feed, schema, schema_v1, sample, session = setup_governance_data
    ro_headers = {"Authorization": f"Bearer {readonly_token}"}
    eng_headers = {"Authorization": f"Bearer {engineer_token}"}

    # 1. READ_ONLY fails to create rule -> 403
    fail_create = client.post(
        "/api/v1/rules",
        headers=ro_headers,
        json={
            "feed_id": str(feed.id),
            "name": "rbac_rule",
            "target_field": "amount",
            "rule_type": "NOT_NULL",
        },
    )
    assert fail_create.status_code == 403

    # Engineer creates rule
    c_res = client.post(
        "/api/v1/rules",
        headers=eng_headers,
        json={
            "feed_id": str(feed.id),
            "name": "rbac_rule",
            "target_field": "amount",
            "rule_type": "NOT_NULL",
        },
    )
    rule_id = c_res.json()["id"]
    version_id = c_res.json()["draft_version"]["id"]

    # 2. READ_ONLY can view and validate -> 200
    assert client.get(f"/api/v1/rules/feed/{feed.id}", headers=ro_headers).status_code == 200
    assert client.get(f"/api/v1/rules/{rule_id}", headers=ro_headers).status_code == 200
    assert client.get(f"/api/v1/rules/{rule_id}/versions/{version_id}", headers=ro_headers).status_code == 200
    assert client.post(f"/api/v1/rules/{rule_id}/versions/{version_id}/validate", headers=ro_headers).status_code == 200

    # 3. READ_ONLY mutations all return 403
    assert client.put(f"/api/v1/rules/{rule_id}/versions/{version_id}", headers=ro_headers, json={"severity": "WARNING"}).status_code == 403
    assert client.post(f"/api/v1/rules/{rule_id}/versions/{version_id}/test", headers=ro_headers).status_code == 403
    assert client.post(f"/api/v1/rules/{rule_id}/versions/{version_id}/publish", headers=ro_headers, json={}).status_code == 403
    assert client.post(f"/api/v1/rules/{rule_id}/versions", headers=ro_headers, json={}).status_code == 403
    assert client.delete(f"/api/v1/rules/{rule_id}", headers=ro_headers).status_code == 403


# Test 27
def test_rule_audit_all_six_events(client, engineer_token, db, setup_governance_data):
    feed, schema, schema_v1, sample, session = setup_governance_data
    headers = {"Authorization": f"Bearer {engineer_token}"}

    # 1. rule.created
    c_res = client.post(
        "/api/v1/rules",
        headers=headers,
        json={"feed_id": str(feed.id), "name": "audit_test_rule", "target_field": "amount", "rule_type": "NOT_NULL"},
    )
    rule_id = c_res.json()["id"]
    v1_id = c_res.json()["draft_version"]["id"]

    # 2. rule.draft_updated
    client.put(f"/api/v1/rules/{rule_id}/versions/{v1_id}", headers=headers, json={"severity": "WARNING"})

    # 3. rule.test_executed
    client.post(f"/api/v1/rules/{rule_id}/versions/{v1_id}/test", headers=headers)

    # 4. rule.published
    client.post(f"/api/v1/rules/{rule_id}/versions/{v1_id}/publish", headers=headers, json={})

    # 5. rule.version_created
    client.post(f"/api/v1/rules/{rule_id}/versions", headers=headers, json={})

    # Create a draft-only rule to test rule.deleted
    d_res = client.post(
        "/api/v1/rules",
        headers=headers,
        json={"feed_id": str(feed.id), "name": "to_be_deleted", "target_field": "amount", "rule_type": "NOT_NULL"},
    )
    del_rule_id = d_res.json()["id"]

    # 6. rule.deleted
    client.delete(f"/api/v1/rules/{del_rule_id}", headers=headers)

    # Inspect all audit events for these rules
    all_actions = [
        AuditActionEnum.RULE_CREATED,
        AuditActionEnum.RULE_DRAFT_UPDATED,
        AuditActionEnum.RULE_VERSION_CREATED,
        AuditActionEnum.RULE_PUBLISHED,
        AuditActionEnum.RULE_TEST_EXECUTED,
        AuditActionEnum.RULE_DELETED,
    ]

    events = db.query(AuditEvent).filter(AuditEvent.action.in_(all_actions)).all()
    found_actions = {e.action for e in events}
    for a in all_actions:
        assert a in found_actions, f"Missing audit event for action {a}"

    # Ensure ZERO sample/data values in before_state or after_state
    for e in events:
        state_str = str(e.after_state or {}) + str(e.before_state or {})
        assert "CLM-01" not in state_str
        assert "CLM-02" not in state_str


# Test 28
def test_step4_published_rule_valid_with_newer_draft(client, engineer_token, db, setup_governance_data):
    feed, schema, schema_v1, sample, session = setup_governance_data
    headers = {"Authorization": f"Bearer {engineer_token}"}

    # Case A: Rule exists but ONLY DRAFT -> Step 4 completion must FAIL
    c_res = client.post(
        "/api/v1/rules",
        headers=headers,
        json={"feed_id": str(feed.id), "name": "step4_draft_rule", "target_field": "amount", "rule_type": "NOT_NULL"},
    )
    rule_id = c_res.json()["id"]
    v1_id = c_res.json()["draft_version"]["id"]

    fail_step = client.put(
        f"/api/v1/onboarding/feed/{feed.id}/step",
        headers=headers,
        json={"current_step": 5, "mark_step_completed": 4},
    )
    assert fail_step.status_code == 400
    assert "unpublished draft-only" in fail_step.json()["detail"].lower()

    # Case B: Publish v1 -> Step 4 completion SUCCEEDS
    client.post(f"/api/v1/rules/{rule_id}/versions/{v1_id}/publish", headers=headers, json={})

    success_step1 = client.put(
        f"/api/v1/onboarding/feed/{feed.id}/step",
        headers=headers,
        json={"current_step": 5, "mark_step_completed": 4},
    )
    assert success_step1.status_code == 200

    # Case C: Spawn v2 DRAFT (v1 is still PUBLISHED) -> Step 4 completion still SUCCEEDS
    client.post(f"/api/v1/rules/{rule_id}/versions", headers=headers, json={})

    success_step2 = client.put(
        f"/api/v1/onboarding/feed/{feed.id}/step",
        headers=headers,
        json={"current_step": 5, "mark_step_completed": 4},
    )
    assert success_step2.status_code == 200


# Test 29
def test_rule_test_results_zero_sample_values_persisted(client, engineer_token, db, setup_governance_data):
    feed, schema, schema_v1, sample, session = setup_governance_data
    headers = {"Authorization": f"Bearer {engineer_token}"}

    c_res = client.post(
        "/api/v1/rules",
        headers=headers,
        json={"feed_id": str(feed.id), "name": "isolation_check", "target_field": "amount", "rule_type": "RANGE", "rule_config": {"min": 500}},
    )
    rule_id = c_res.json()["id"]
    v1_id = c_res.json()["draft_version"]["id"]

    # Execute test
    t_res = client.post(f"/api/v1/rules/{rule_id}/versions/{v1_id}/test", headers=headers)
    assert t_res.status_code == 200

    # Query rule_test_runs table directly in database
    run_record = db.query(RuleTestRun).filter(RuleTestRun.rule_version_id == uuid.UUID(v1_id)).first()
    assert run_record is not None
    assert run_record.failed_rows == 2

    # Check each detail entry: ONLY row_number, field_name, reason
    for item in run_record.failed_row_details:
        assert set(item.keys()) == {"row_number", "field_name", "reason"}
        # Must NOT contain actual value (100 or 200)
        assert "100" not in str(item["reason"])
        assert "200" not in str(item["reason"])
