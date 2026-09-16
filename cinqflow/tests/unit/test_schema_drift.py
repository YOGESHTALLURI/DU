"""
Unit Tests for Deterministic Schema Drift Detection — Wave 2 Slice 1 (CF-V2-E5-04)
"""
import uuid
import pytest
from backend.models.schema import SchemaField, SchemaDataTypeEnum, SchemaVersion, SchemaVersionStatusEnum
from backend.models.drift import DriftSeverityEnum
from backend.engine.drift_detector import SchemaDriftDetector


def _build_dummy_schema_version():
    sv = SchemaVersion(
        id=uuid.uuid4(),
        schema_id=uuid.uuid4(),
        version_number=1,
        status=SchemaVersionStatusEnum.PUBLISHED,
        created_by="engineer",
        updated_by="engineer",
    )
    sv.fields = [
        SchemaField(
            id=uuid.uuid4(),
            schema_version_id=sv.id,
            field_name="member_id",
            data_type=SchemaDataTypeEnum.STRING,
            is_required=True,
            created_by="engineer",
            updated_by="engineer",
        ),
        SchemaField(
            id=uuid.uuid4(),
            schema_version_id=sv.id,
            field_name="first_name",
            data_type=SchemaDataTypeEnum.STRING,
            is_required=True,
            created_by="engineer",
            updated_by="engineer",
        ),
        SchemaField(
            id=uuid.uuid4(),
            schema_version_id=sv.id,
            field_name="middle_name",
            data_type=SchemaDataTypeEnum.STRING,
            is_required=False,
            created_by="engineer",
            updated_by="engineer",
        ),
        SchemaField(
            id=uuid.uuid4(),
            schema_version_id=sv.id,
            field_name="dob",
            data_type=SchemaDataTypeEnum.DATE,
            is_required=True,
            created_by="engineer",
            updated_by="engineer",
        ),
    ]
    return sv


def test_drift_exact_match_returns_none_severity():
    sv = _build_dummy_schema_version()
    raw = b"member_id,first_name,middle_name,dob\nM001,John,A,1990-01-01\n"
    res = SchemaDriftDetector.detect_drift(raw, sv, expected_delimiter=",")
    assert res.drift_severity == DriftSeverityEnum.NONE
    assert len(res.missing_fields) == 0
    assert len(res.unexpected_fields) == 0


def test_drift_missing_required_column_is_breaking():
    sv = _build_dummy_schema_version()
    # Missing 'dob' and 'first_name' which are required
    raw = b"member_id,middle_name\nM001,A\n"
    res = SchemaDriftDetector.detect_drift(raw, sv, expected_delimiter=",")
    assert res.drift_severity == DriftSeverityEnum.BREAKING
    assert "dob" in res.missing_required
    assert "first_name" in res.missing_required
    assert "BREAKING" in res.summary


def test_drift_missing_optional_column_is_non_breaking():
    sv = _build_dummy_schema_version()
    # Missing 'middle_name' which is optional (is_required=False)
    raw = b"member_id,first_name,dob\nM001,John,1990-01-01\n"
    res = SchemaDriftDetector.detect_drift(raw, sv, expected_delimiter=",")
    assert res.drift_severity == DriftSeverityEnum.NON_BREAKING
    assert res.missing_optional == ["middle_name"]
    assert len(res.missing_required) == 0


def test_drift_unexpected_extra_column_is_non_breaking():
    sv = _build_dummy_schema_version()
    # All expected present + 'phone_number' and 'plan_code' unexpected
    raw = b"member_id,first_name,middle_name,dob,phone_number,plan_code\nM001,John,A,1990-01-01,555-1234,GOLD\n"
    res = SchemaDriftDetector.detect_drift(raw, sv, expected_delimiter=",")
    assert res.drift_severity == DriftSeverityEnum.NON_BREAKING
    assert "phone_number" in res.unexpected_fields
    assert "plan_code" in res.unexpected_fields
    assert len(res.missing_fields) == 0


def test_drift_delimiter_mismatch_is_breaking():
    sv = _build_dummy_schema_version()
    # File is pipe-delimited, but contract expects comma
    raw = b"member_id|first_name|middle_name|dob\nM001|John|A|1990-01-01\n"
    res = SchemaDriftDetector.detect_drift(raw, sv, expected_delimiter=",")
    assert res.drift_severity == DriftSeverityEnum.BREAKING
    assert res.detected_delimiter == "|"
    assert "Delimiter mismatch" in res.summary


def test_drift_unparseable_header_is_breaking():
    sv = _build_dummy_schema_version()
    # Empty bytes
    res_empty = SchemaDriftDetector.detect_drift(b"", sv, expected_delimiter=",")
    assert res_empty.drift_severity == DriftSeverityEnum.BREAKING

    # Whitespace only
    res_ws = SchemaDriftDetector.detect_drift(b"   \n   \n", sv, expected_delimiter=",")
    assert res_ws.drift_severity == DriftSeverityEnum.BREAKING


def test_drift_multiple_conditions_precedence():
    sv = _build_dummy_schema_version()
    # Missing required 'dob' AND missing optional 'middle_name' AND unexpected 'country'
    raw = b"member_id,first_name,country\nM001,John,USA\n"
    res = SchemaDriftDetector.detect_drift(raw, sv, expected_delimiter=",")
    # Precedence: ANY breaking condition makes overall severity BREAKING
    assert res.drift_severity == DriftSeverityEnum.BREAKING
    assert "dob" in res.missing_required
    assert "middle_name" in res.missing_optional
    assert "country" in res.unexpected_fields


def test_drift_zero_phi_leakage():
    sv = _build_dummy_schema_version()
    # Row contains identifiable data: 1990-01-01, John, Doe, SSN-999
    raw = b"member_id,first_name,dob\nM001,John,1990-01-01\n"
    res = SchemaDriftDetector.detect_drift(raw, sv, expected_delimiter=",")
    report_repr = str(res.__dict__)
    # Verify zero data cell values in report
    assert "John" not in report_repr
    assert "1990-01-01" not in report_repr
    assert "M001" not in report_repr
