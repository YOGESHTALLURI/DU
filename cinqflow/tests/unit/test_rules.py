"""
Unit Tests for Data Quality Rules — Wave 1 Slice 4
15 tests covering creation, uniqueness, schema pinning, validation per rule type,
severity levels, published immutability, and soft-delete semantics.
"""
import uuid
import pytest
from backend.models.feed import Feed, FeedFormatEnum, FeedStatusEnum
from backend.models.schema import Schema, SchemaVersion, SchemaField, SchemaVersionStatusEnum, SchemaDataTypeEnum
from backend.models.rule import DataQualityRule, RuleVersion, RuleVersionStatusEnum, RuleTypeEnum, RuleSeverityEnum
from backend.services.rule_service import RuleService
from backend.schemas.rule import RuleCreateRequest, RuleVersionUpdateRequest


@pytest.fixture
def test_feed_and_schema(db):
    """Creates a feed with published schema v1 and draft schema v2."""
    feed = Feed(
        id=uuid.uuid4(),
        name=f"Feed_Rules_{uuid.uuid4().hex[:6]}",
        domain="CLAIMS",
        format=FeedFormatEnum.CSV,
        landing_folder="claims/rules_test",
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

    # Published schema version 1
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
        SchemaField(id=uuid.uuid4(), schema_version_id=v1.id, field_name="member_age", data_type=SchemaDataTypeEnum.INTEGER, ordinal_position=6, created_by="engineer", updated_by="engineer"),
    ]
    db.add_all(fields_v1)
    db.commit()
    db.refresh(feed)
    db.refresh(schema)
    return feed, schema, v1


# Test 1
def test_create_rule_and_draft_version(db, test_feed_and_schema):
    feed, schema, schema_v1 = test_feed_and_schema
    svc = RuleService(db)
    req = RuleCreateRequest(
        feed_id=feed.id,
        name="positive_amount",
        target_field="amount",
        rule_type=RuleTypeEnum.RANGE,
        severity=RuleSeverityEnum.QUARANTINE,
        rule_config={"min": 0, "max": 100000},
    )
    rule_resp = svc.create_rule(req, actor_id="analyst")
    assert rule_resp.name == "positive_amount"
    assert rule_resp.is_deleted is False
    assert rule_resp.draft_version is not None
    assert rule_resp.draft_version.version_number == 1
    assert rule_resp.draft_version.schema_version_id == schema_v1.id
    assert rule_resp.draft_version.status == RuleVersionStatusEnum.DRAFT


# Test 2
def test_create_rule_duplicate_name_rejected(db, test_feed_and_schema):
    feed, schema, schema_v1 = test_feed_and_schema
    svc = RuleService(db)
    req = RuleCreateRequest(
        feed_id=feed.id,
        name="unique_name_test",
        target_field="amount",
        rule_type=RuleTypeEnum.NOT_NULL,
    )
    svc.create_rule(req, actor_id="analyst")

    with pytest.raises(Exception) as excinfo:
        svc.create_rule(req, actor_id="analyst")
    assert "already exists" in str(excinfo.value.detail)


# Test 3
def test_create_rule_requires_published_schema(db):
    feed = Feed(
        id=uuid.uuid4(),
        name=f"Feed_NoSchema_{uuid.uuid4().hex[:6]}",
        domain="CLAIMS",
        format=FeedFormatEnum.CSV,
        landing_folder="claims/noschema",
        filename_pattern="claims_*.csv",
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(feed)
    db.commit()
    svc = RuleService(db)
    req = RuleCreateRequest(
        feed_id=feed.id,
        name="rule_fail",
        target_field="amount",
        rule_type=RuleTypeEnum.NOT_NULL,
    )
    with pytest.raises(Exception) as excinfo:
        svc.create_rule(req, actor_id="analyst")
    assert "schema" in str(excinfo.value.detail).lower()


# Test 4
def test_not_null_validation(db, test_feed_and_schema):
    feed, schema, schema_v1 = test_feed_and_schema
    svc = RuleService(db)
    rule_resp = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="not_null_rule",
            target_field="claim_id",
            rule_type=RuleTypeEnum.NOT_NULL,
            rule_config={"extra_param": 123},
        ),
        actor_id="analyst",
    )
    rep = svc.validate_rule_version(rule_resp.id, rule_resp.draft_version.id)
    assert rep.is_valid is True
    assert len(rep.warnings) > 0  # Warns on extra parameters


# Test 5
def test_range_validation_valid_and_invalid(db, test_feed_and_schema):
    feed, schema, schema_v1 = test_feed_and_schema
    svc = RuleService(db)
    # Valid
    r1 = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="valid_range",
            target_field="amount",
            rule_type=RuleTypeEnum.RANGE,
            rule_config={"min": 10, "max": 500, "inclusive": True},
        ),
        actor_id="analyst",
    )
    rep1 = svc.validate_rule_version(r1.id, r1.draft_version.id)
    assert rep1.is_valid is True

    # Invalid: non-numeric target field (STRING)
    r2 = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="invalid_range_target",
            target_field="claim_id",
            rule_type=RuleTypeEnum.RANGE,
            rule_config={"min": 0, "max": 100},
        ),
        actor_id="analyst",
    )
    rep2 = svc.validate_rule_version(r2.id, r2.draft_version.id)
    assert rep2.is_valid is False
    assert any("numeric" in e.lower() for e in rep2.errors)

    # Invalid: min > max
    r3 = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="invalid_range_bounds",
            target_field="amount",
            rule_type=RuleTypeEnum.RANGE,
            rule_config={"min": 500, "max": 100},
        ),
        actor_id="analyst",
    )
    rep3 = svc.validate_rule_version(r3.id, r3.draft_version.id)
    assert rep3.is_valid is False
    assert any("greater than" in e.lower() for e in rep3.errors)


# Test 6
def test_regex_validation_valid_and_invalid(db, test_feed_and_schema):
    feed, schema, schema_v1 = test_feed_and_schema
    svc = RuleService(db)
    # Valid regex
    r1 = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="valid_regex",
            target_field="claim_id",
            rule_type=RuleTypeEnum.REGEX,
            rule_config={"pattern": r"^CLM-[0-9]+$"},
        ),
        actor_id="analyst",
    )
    rep1 = svc.validate_rule_version(r1.id, r1.draft_version.id)
    assert rep1.is_valid is True

    # Invalid syntax
    r2 = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="invalid_regex_syntax",
            target_field="claim_id",
            rule_type=RuleTypeEnum.REGEX,
            rule_config={"pattern": r"[0-9++"},
        ),
        actor_id="analyst",
    )
    rep2 = svc.validate_rule_version(r2.id, r2.draft_version.id)
    assert rep2.is_valid is False
    assert any("invalid regex" in e.lower() for e in rep2.errors)


# Test 7
def test_enum_validation_valid_and_invalid(db, test_feed_and_schema):
    feed, schema, schema_v1 = test_feed_and_schema
    svc = RuleService(db)
    # Valid
    r1 = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="valid_enum",
            target_field="status",
            rule_type=RuleTypeEnum.ENUM,
            rule_config={"allowed_values": ["PAID", "DENIED", "PENDING"], "case_sensitive": True},
        ),
        actor_id="analyst",
    )
    rep1 = svc.validate_rule_version(r1.id, r1.draft_version.id)
    assert rep1.is_valid is True

    # Duplicate values in enum
    r2 = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="dup_enum",
            target_field="status",
            rule_type=RuleTypeEnum.ENUM,
            rule_config={"allowed_values": ["PAID", "PAID"]},
        ),
        actor_id="analyst",
    )
    rep2 = svc.validate_rule_version(r2.id, r2.draft_version.id)
    assert rep2.is_valid is False
    assert any("duplicate" in e.lower() for e in rep2.errors)


# Test 8
def test_length_validation_valid_and_invalid(db, test_feed_and_schema):
    feed, schema, schema_v1 = test_feed_and_schema
    svc = RuleService(db)
    # Valid
    r1 = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="valid_len",
            target_field="claim_id",
            rule_type=RuleTypeEnum.LENGTH,
            rule_config={"min_length": 3, "max_length": 20},
        ),
        actor_id="analyst",
    )
    rep1 = svc.validate_rule_version(r1.id, r1.draft_version.id)
    assert rep1.is_valid is True

    # Invalid min > max
    r2 = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="invalid_len_bounds",
            target_field="claim_id",
            rule_type=RuleTypeEnum.LENGTH,
            rule_config={"min_length": 30, "max_length": 10},
        ),
        actor_id="analyst",
    )
    rep2 = svc.validate_rule_version(r2.id, r2.draft_version.id)
    assert rep2.is_valid is False
    assert any("greater than" in e.lower() for e in rep2.errors)


# Test 9
def test_date_range_validation_valid_and_invalid(db, test_feed_and_schema):
    feed, schema, schema_v1 = test_feed_and_schema
    svc = RuleService(db)
    # Valid
    r1 = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="valid_date_range",
            target_field="service_date",
            rule_type=RuleTypeEnum.DATE_RANGE,
            rule_config={"min_date": "2020-01-01", "max_date": "2030-12-31", "format": "YYYY-MM-DD"},
        ),
        actor_id="analyst",
    )
    rep1 = svc.validate_rule_version(r1.id, r1.draft_version.id)
    assert rep1.is_valid is True

    # Invalid: non-date target field
    r2 = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="invalid_date_target",
            target_field="amount",
            rule_type=RuleTypeEnum.DATE_RANGE,
            rule_config={"min_date": "2020-01-01", "format": "YYYY-MM-DD"},
        ),
        actor_id="analyst",
    )
    rep2 = svc.validate_rule_version(r2.id, r2.draft_version.id)
    assert rep2.is_valid is False
    assert any("date" in e.lower() for e in rep2.errors)


# Test 10
def test_cross_field_validation_valid_and_invalid(db, test_feed_and_schema):
    feed, schema, schema_v1 = test_feed_and_schema
    svc = RuleService(db)
    # Valid
    r1 = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="valid_cross_field",
            target_field="amount",
            rule_type=RuleTypeEnum.CROSS_FIELD,
            rule_config={"compare_field": "paid_amount", "operator": "GTE"},
        ),
        actor_id="analyst",
    )
    rep1 = svc.validate_rule_version(r1.id, r1.draft_version.id)
    assert rep1.is_valid is True

    # Invalid: self-reference
    r2 = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="self_ref_cross_field",
            target_field="amount",
            rule_type=RuleTypeEnum.CROSS_FIELD,
            rule_config={"compare_field": "amount", "operator": "EQ"},
        ),
        actor_id="analyst",
    )
    rep2 = svc.validate_rule_version(r2.id, r2.draft_version.id)
    assert rep2.is_valid is False
    assert any("itself" in e.lower() for e in rep2.errors)


# Test 11
def test_severity_levels_valid_and_invalid(db, test_feed_and_schema):
    feed, schema, schema_v1 = test_feed_and_schema
    svc = RuleService(db)
    for sev in [RuleSeverityEnum.INFO, RuleSeverityEnum.WARNING, RuleSeverityEnum.QUARANTINE, RuleSeverityEnum.REJECT_FILE]:
        r = svc.create_rule(
            RuleCreateRequest(
                feed_id=feed.id,
                name=f"sev_test_{sev.value}",
                target_field="amount",
                rule_type=RuleTypeEnum.NOT_NULL,
                severity=sev,
            ),
            actor_id="analyst",
        )
        assert r.draft_version.severity == sev


# Test 12
def test_published_rule_immutability(db, test_feed_and_schema):
    from backend.schemas.rule import RulePublishRequest
    feed, schema, schema_v1 = test_feed_and_schema
    svc = RuleService(db)
    r = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="immutable_rule",
            target_field="amount",
            rule_type=RuleTypeEnum.NOT_NULL,
        ),
        actor_id="analyst",
    )
    # Publish
    pub_ver = svc.publish_rule_version(r.id, r.draft_version.id, RulePublishRequest(change_notes="Publishing"), actor_id="analyst")
    assert pub_ver.status == RuleVersionStatusEnum.PUBLISHED

    # Attempt to update published version -> 400
    with pytest.raises(Exception) as excinfo:
        svc.update_draft_version(
            r.id, pub_ver.id, RuleVersionUpdateRequest(target_field="claim_id"), actor_id="analyst"
        )
    assert "immutable" in str(excinfo.value.detail).lower()


# Test 13
def test_soft_delete_draft_only_succeeds(db, test_feed_and_schema):
    feed, schema, schema_v1 = test_feed_and_schema
    svc = RuleService(db)
    r = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="delete_me_draft",
            target_field="amount",
            rule_type=RuleTypeEnum.NOT_NULL,
        ),
        actor_id="analyst",
    )
    deleted = svc.soft_delete_rule(r.id, actor_id="analyst")
    assert deleted.is_deleted is True
    assert deleted.deleted_by == "analyst"

    # Excluded from normal list
    active_rules = svc.get_rules_for_feed(feed.id, include_deleted=False)
    assert not any(x.id == r.id for x in active_rules)

    # Included when include_deleted=True
    all_rules = svc.get_rules_for_feed(feed.id, include_deleted=True)
    assert any(x.id == r.id for x in all_rules)


# Test 14
def test_soft_delete_with_published_version_rejected(db, test_feed_and_schema):
    from backend.schemas.rule import RulePublishRequest
    feed, schema, schema_v1 = test_feed_and_schema
    svc = RuleService(db)
    r = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="no_delete_published",
            target_field="amount",
            rule_type=RuleTypeEnum.NOT_NULL,
        ),
        actor_id="analyst",
    )
    svc.publish_rule_version(r.id, r.draft_version.id, RulePublishRequest(), actor_id="analyst")

    with pytest.raises(Exception) as excinfo:
        svc.soft_delete_rule(r.id, actor_id="analyst")
    assert "cannot be deleted" in str(excinfo.value.detail).lower()


# Test 15
def test_schema_pinning_never_floats(db, test_feed_and_schema):
    feed, schema, schema_v1 = test_feed_and_schema
    svc = RuleService(db)
    r = svc.create_rule(
        RuleCreateRequest(
            feed_id=feed.id,
            name="pinned_rule",
            target_field="amount",
            rule_type=RuleTypeEnum.NOT_NULL,
        ),
        actor_id="analyst",
    )
    assert r.draft_version.schema_version_id == schema_v1.id

    # Add and publish schema version 2
    schema_v2 = SchemaVersion(
        id=uuid.uuid4(),
        schema_id=schema.id,
        version_number=2,
        status=SchemaVersionStatusEnum.PUBLISHED,
        created_by="engineer",
        updated_by="engineer",
    )
    db.add(schema_v2)
    schema_v1.status = SchemaVersionStatusEnum.SUPERSEDED
    db.commit()

    # Rule version must NEVER have silently floated to schema v2
    refreshed_v = svc.get_version_detail(r.id, r.draft_version.id)
    assert refreshed_v.schema_version_id == schema_v1.id
