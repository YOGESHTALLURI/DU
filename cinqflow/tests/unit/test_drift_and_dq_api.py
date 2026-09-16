"""
API & RBAC Unit Tests for Schema Drift & DQ Executions Endpoints — Wave 2 Slice 1
"""
import uuid
import pytest
from backend.models.drift import SchemaDriftReport, DriftSeverityEnum, DriftStatusEnum
from backend.models.dq_result import DQResult, DQActionTakenEnum
from backend.models.pipeline import Batch, BatchStage, StageNameEnum, StageStatusEnum, BatchStatusEnum
from backend.models.feed import Feed, FeedFormatEnum, FeedStatusEnum, FeedVersion, FeedVersionStatusEnum
from backend.models.schema import Schema, SchemaVersion, SchemaVersionStatusEnum
from backend.models.rule import DataQualityRule, RuleVersion, RuleVersionStatusEnum, RuleTypeEnum, RuleSeverityEnum


@pytest.fixture
def api_test_data(db):
    prefix = uuid.uuid4().hex[:6]

    feed = Feed(
        id=uuid.uuid4(),
        name=f"API_FEED_{prefix}",
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
        name=f"Schema {prefix}",
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

    batch = Batch(
        id=uuid.uuid4(),
        feed_id=feed.id,
        feed_version_id=fv.id,
        status=BatchStatusEnum.SUCCESS,
        triggered_by="engineer",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(batch)
    db.flush()

    stage = BatchStage(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_name=StageNameEnum.SILVER_RAW,
        stage_order=3,
        status=StageStatusEnum.SUCCESS,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(stage)
    db.flush()

    # Non-breaking drift report
    drift_nb = SchemaDriftReport(
        id=uuid.uuid4(),
        batch_id=batch.id,
        feed_id=feed.id,
        expected_schema_version_id=sv.id,
        drift_severity=DriftSeverityEnum.NON_BREAKING,
        unexpected_fields=["extra_col"],
        status=DriftStatusEnum.DETECTED,
        created_by="engineer",
        updated_by="engineer",
    )
    # Breaking drift report
    drift_brk = SchemaDriftReport(
        id=uuid.uuid4(),
        batch_id=batch.id,
        feed_id=feed.id,
        expected_schema_version_id=sv.id,
        drift_severity=DriftSeverityEnum.BREAKING,
        missing_fields=["mandatory_col"],
        status=DriftStatusEnum.DETECTED,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add_all([drift_nb, drift_brk])
    db.flush()

    # Rule and DQ Result
    rule = DataQualityRule(
        id=uuid.uuid4(),
        feed_id=feed.id,
        schema_id=schema_obj.id,
        name="api_test_rule",
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
        severity=RuleSeverityEnum.QUARANTINE,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(r_pub)
    db.flush()

    dq = DQResult(
        id=uuid.uuid4(),
        batch_id=batch.id,
        stage_id=stage.id,
        rule_version_id=r_pub.id,
        total_rows_evaluated=100,
        passed_rows=95,
        failed_rows=5,
        pass_rate=95.0,
        action_taken=DQActionTakenEnum.QUARANTINED_ROWS,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(dq)
    db.commit()

    return {
        "feed": feed,
        "batch": batch,
        "drift_nb": drift_nb,
        "drift_brk": drift_brk,
        "rule": rule,
        "rule_version": r_pub,
        "dq_result": dq,
    }


def test_api_get_drift_reports_filter_and_pagination(client, readonly_headers, api_test_data):
    """GET /api/v1/schemas/drift lists reports with filtering and pagination."""
    res = client.get(
        f"/api/v1/schemas/drift?feed_id={api_test_data['feed'].id}&drift_severity=NON_BREAKING",
        headers=readonly_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["drift_severity"] == "NON_BREAKING"


def test_api_acknowledge_non_breaking_drift_engineer(client, engineer_headers, api_test_data):
    """POST /api/v1/schemas/drift/{id}/acknowledge succeeds for ENGINEER on NON_BREAKING report."""
    drift_id = api_test_data["drift_nb"].id
    res = client.post(
        f"/api/v1/schemas/drift/{drift_id}/acknowledge",
        json={"notes": "Contract change planned for next sprint"},
        headers=engineer_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ACKNOWLEDGED"
    assert data["acknowledgement_notes"] == "Contract change planned for next sprint"


def test_api_acknowledge_drift_forbidden_for_readonly_and_analyst(client, readonly_headers, api_test_data):
    """POST /api/v1/schemas/drift/{id}/acknowledge returns 403 Forbidden for READ_ONLY."""
    drift_id = api_test_data["drift_nb"].id
    res = client.post(
        f"/api/v1/schemas/drift/{drift_id}/acknowledge",
        json={"notes": "Read-only attempting to acknowledge"},
        headers=readonly_headers,
    )
    assert res.status_code == 403


def test_api_acknowledge_breaking_drift_rejected(client, engineer_headers, api_test_data):
    """Attempting to acknowledge a BREAKING drift report returns 400 Bad Request."""
    drift_id = api_test_data["drift_brk"].id
    res = client.post(
        f"/api/v1/schemas/drift/{drift_id}/acknowledge",
        json={"notes": "Trying to bypass breaking drift"},
        headers=engineer_headers,
    )
    assert res.status_code == 400
    assert "breaking drift" in res.json()["detail"].lower()


def test_api_get_rules_executions_batch_summary(client, readonly_headers, api_test_data):
    """GET /api/v1/rules/executions/batch/{id} returns batch DQ summary."""
    batch_id = api_test_data["batch"].id
    res = client.get(
        f"/api/v1/rules/executions/batch/{batch_id}",
        headers=readonly_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["batch_id"] == str(batch_id)
    assert data["total_rules_executed"] == 1
    assert data["total_violations"] == 5
    assert data["has_quarantined_rows"] is True
    assert data["batch_action"] == "QUARANTINED_ROWS"
    assert len(data["rules"]) == 1
    assert data["rules"][0]["rule_name"] == "api_test_rule"
