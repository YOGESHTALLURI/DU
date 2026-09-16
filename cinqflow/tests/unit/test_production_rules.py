"""
Unit Tests for Production Data Quality Rules Engine — Wave 2 Slice 1 (CF-V2-E7-05)
"""
import uuid
import pytest
from backend.models.rule import RuleVersion, RuleTypeEnum, RuleSeverityEnum
from backend.engine.production_rules import ProductionRulesEngine


def _dummy_rule_version(rule_type: RuleTypeEnum, target_field: str, config: dict, severity: RuleSeverityEnum = RuleSeverityEnum.QUARANTINE):
    return RuleVersion(
        id=uuid.uuid4(),
        rule_id=uuid.uuid4(),
        version_number=1,
        schema_version_id=uuid.uuid4(),
        rule_type=rule_type,
        target_field=target_field,
        severity=severity,
        rule_config=config,
        created_by="engineer",
        updated_by="engineer",
    )


def test_prod_eval_not_null_rule():
    rv = _dummy_rule_version(RuleTypeEnum.NOT_NULL, "member_id", {})
    # Valid
    violated, _ = ProductionRulesEngine.evaluate_rule_on_value({"member_id": "M123"}, rv)
    assert violated is False

    # Empty string
    violated, reason = ProductionRulesEngine.evaluate_rule_on_value({"member_id": ""}, rv)
    assert violated is True
    assert "null or empty" in reason

    # None
    violated, reason = ProductionRulesEngine.evaluate_rule_on_value({"member_id": None}, rv)
    assert violated is True


def test_prod_eval_range_rule():
    rv = _dummy_rule_version(RuleTypeEnum.RANGE, "amount", {"min": 10.0, "max": 100.0, "inclusive_min": True, "inclusive_max": True})
    # Valid in range
    violated, _ = ProductionRulesEngine.evaluate_rule_on_value({"amount": "50.50"}, rv)
    assert violated is False

    # Below min
    violated, reason = ProductionRulesEngine.evaluate_rule_on_value({"amount": "9.99"}, rv)
    assert violated is True
    assert "below minimum" in reason

    # Above max
    violated, reason = ProductionRulesEngine.evaluate_rule_on_value({"amount": "100.01"}, rv)
    assert violated is True
    assert "exceeds maximum" in reason

    # Non-numeric
    violated, reason = ProductionRulesEngine.evaluate_rule_on_value({"amount": "abc"}, rv)
    assert violated is True
    assert "not numeric" in reason


def test_prod_eval_regex_rule():
    # SSN pattern: 3 digits - 2 digits - 4 digits
    rv = _dummy_rule_version(RuleTypeEnum.REGEX, "ssn", {"pattern": r"^\d{3}-\d{2}-\d{4}$"})
    violated, _ = ProductionRulesEngine.evaluate_rule_on_value({"ssn": "123-45-6789"}, rv)
    assert violated is False

    violated, reason = ProductionRulesEngine.evaluate_rule_on_value({"ssn": "123456789"}, rv)
    assert violated is True
    assert "does not match pattern" in reason


def test_prod_eval_enum_rule():
    rv = _dummy_rule_version(RuleTypeEnum.ENUM, "status", {"allowed_values": ["ACTIVE", "INACTIVE", "PENDING"], "case_sensitive": False})
    # Case insensitive match
    violated, _ = ProductionRulesEngine.evaluate_rule_on_value({"status": "active"}, rv)
    assert violated is False

    violated, reason = ProductionRulesEngine.evaluate_rule_on_value({"status": "CANCELLED"}, rv)
    assert violated is True
    assert "not in allowed set" in reason


def test_prod_eval_length_rule():
    rv = _dummy_rule_version(RuleTypeEnum.LENGTH, "zip_code", {"exact_length": 5})
    violated, _ = ProductionRulesEngine.evaluate_rule_on_value({"zip_code": "90210"}, rv)
    assert violated is False

    violated, reason = ProductionRulesEngine.evaluate_rule_on_value({"zip_code": "9021"}, rv)
    assert violated is True
    assert "exact length" in reason


def test_prod_eval_date_range_rule():
    rv = _dummy_rule_version(
        RuleTypeEnum.DATE_RANGE,
        "service_date",
        {"format": "%Y-%m-%d", "min_date": "2020-01-01", "max_date": "2025-12-31"}
    )
    violated, _ = ProductionRulesEngine.evaluate_rule_on_value({"service_date": "2023-06-15"}, rv)
    assert violated is False

    # Out of range (prior to 2020)
    violated, reason = ProductionRulesEngine.evaluate_rule_on_value({"service_date": "2019-12-31"}, rv)
    assert violated is True
    assert "prior to minimum date" in reason

    # Invalid format
    violated, reason = ProductionRulesEngine.evaluate_rule_on_value({"service_date": "15/06/2023"}, rv)
    assert violated is True
    assert "does not match format" in reason


def test_prod_eval_cross_field_rule():
    rv = _dummy_rule_version(
        RuleTypeEnum.CROSS_FIELD,
        "end_date",
        {"secondary_field": "start_date", "operator": "GREATER_THAN"}
    )
    # Valid numeric comparison: 100 > 50
    violated, _ = ProductionRulesEngine.evaluate_rule_on_value({"end_date": "100", "start_date": "50"}, rv)
    assert violated is False

    # Invalid: 40 not > 50
    violated, reason = ProductionRulesEngine.evaluate_rule_on_value({"end_date": "40", "start_date": "50"}, rv)
    assert violated is True
    assert "not greater than" in reason


def test_prod_eval_null_handling_semantics():
    # When a non-NOT_NULL rule encounters null or empty, it skips evaluation
    rv_range = _dummy_rule_version(RuleTypeEnum.RANGE, "optional_score", {"min": 1, "max": 10})
    violated, _ = ProductionRulesEngine.evaluate_rule_on_value({"optional_score": None}, rv_range)
    assert violated is False

    violated, _ = ProductionRulesEngine.evaluate_rule_on_value({"optional_score": ""}, rv_range)
    assert violated is False
