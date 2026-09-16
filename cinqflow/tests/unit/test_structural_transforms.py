"""
Unit Tests for Structural Transform Engine — Wave 3 Slice 1 (CF-V3-E6-05)
"""
import pytest
from backend.models.mapping import TransformTypeEnum
from backend.engine.structural_transforms import (
    extract_path,
    apply_explode,
    apply_flatten,
    apply_path_extract,
    apply_array_map,
    apply_unnest,
    StructuralTransformEngine,
)


def test_extract_path_simple_and_nested():
    data = {
        "patient": {
            "id": "P12345",
            "name": {
                "family": "Smith",
                "given": "Alice"
            }
        }
    }
    assert extract_path(data, "patient.id") == "P12345"
    assert extract_path(data, "patient.name.family") == "Smith"
    assert extract_path(data, "patient.name.given") == "Alice"
    assert extract_path(data, "patient.nonexistent", default="N/A") == "N/A"
    assert extract_path(None, "patient.id") is None


def test_extract_path_array_index_and_wildcard():
    data = {
        "entry": [
            {"resource": {"id": "res-1", "type": "Patient"}},
            {"resource": {"id": "res-2", "type": "Observation"}},
            {"resource": {"id": "res-3", "type": "Encounter"}}
        ]
    }
    assert extract_path(data, "entry[0].resource.id") == "res-1"
    assert extract_path(data, "entry[1].resource.type") == "Observation"
    assert extract_path(data, "entry[99].resource.id", default=None) is None
    # Wildcard extraction
    assert extract_path(data, "entry[*].resource.id") == ["res-1", "res-2", "res-3"]


def test_extract_path_with_filter():
    data = {
        "telecom": [
            {"system": "email", "value": "alice@example.com"},
            {"system": "phone", "value": "555-0199"},
            {"system": "pager", "value": "555-0100"}
        ]
    }
    phone = extract_path(data, "telecom[?(@.system=='phone')].value")
    assert phone == "555-0199"

    email = extract_path(data, "telecom[?(@.system=='email')].value")
    assert email == "alice@example.com"


def test_apply_explode():
    record = {
        "claim_id": "CLM-999",
        "patient_id": "P-100",
        "diagnoses": ["E11.9", "I10", "Z79.4"]
    }
    exploded = apply_explode(record, array_path="diagnoses", target_field="diagnosis_code")
    assert len(exploded) == 3
    assert exploded[0]["claim_id"] == "CLM-999"
    assert exploded[0]["diagnosis_code"] == "E11.9"
    assert exploded[0]["_explode_index"] == 0
    assert exploded[1]["diagnosis_code"] == "I10"
    assert exploded[2]["diagnosis_code"] == "Z79.4"

    # Outer join with empty array
    empty_record = {"claim_id": "CLM-000", "diagnoses": []}
    exploded_empty = apply_explode(empty_record, array_path="diagnoses", target_field="diagnosis_code", outer_join=True)
    assert len(exploded_empty) == 1
    assert exploded_empty[0]["diagnosis_code"] is None

    # Inner join with empty array
    exploded_inner = apply_explode(empty_record, array_path="diagnoses", target_field="diagnosis_code", outer_join=False)
    assert len(exploded_inner) == 0


def test_apply_flatten():
    nested = {
        "patient": {
            "name": {
                "first": "John",
                "last": "Doe"
            },
            "age": 42
        },
        "status": "active"
    }
    flat = apply_flatten(nested, prefix="", separator="_", max_depth=5)
    assert flat["patient_name_first"] == "John"
    assert flat["patient_name_last"] == "Doe"
    assert flat["patient_age"] == 42
    assert flat["status"] == "active"


def test_apply_path_extract():
    data = {"resource": {"identifier": [{"system": "MRN", "value": "MRN-555"}]}}
    val = apply_path_extract(data, "resource.identifier[0].value")
    assert val == "MRN-555"


def test_apply_array_map():
    data = {
        "coding": [
            {"code": "8480-6", "display": "Systolic BP"},
            {"code": "8462-4", "display": "Diastolic BP"}
        ]
    }
    codes_str = apply_array_map(data, array_path="coding", element_path="code", delimiter=" | ")
    assert codes_str == "8480-6 | 8462-4"

    codes_list = apply_array_map(data, array_path="coding", element_path="code", delimiter=None)
    assert codes_list == ["8480-6", "8462-4"]


def test_apply_unnest():
    data = {
        "member_id": "M123",
        "demographics": {
            "dob": "1990-05-12",
            "gender": "F",
            "marital_status": "S"
        }
    }
    unnested = apply_unnest(data, path="demographics", properties=["dob", "gender"])
    assert unnested == {"dob": "1990-05-12", "gender": "F"}


def test_structural_transform_engine_dispatch():
    # 1. EXPLODE
    row = {"items": ["apple", "banana"]}
    res = StructuralTransformEngine.evaluate(
        transform_type=TransformTypeEnum.EXPLODE,
        transform_params={"array_path": "items"},
        source_fields=["items"],
        row_or_obj=row,
    )
    assert res == "apple"

    # 2. FLATTEN
    row = {"a": {"b": 1, "c": 2}}
    res = StructuralTransformEngine.evaluate(
        transform_type=TransformTypeEnum.FLATTEN,
        transform_params={"separator": "."},
        source_fields=[],
        row_or_obj=row,
    )
    assert res == {"a.b": 1, "a.c": 2}

    # 3. PATH_EXTRACT
    row = {"patient": {"id": "123"}}
    res = StructuralTransformEngine.evaluate(
        transform_type=TransformTypeEnum.PATH_EXTRACT,
        transform_params={"path": "patient.id"},
        source_fields=[],
        row_or_obj=row,
    )
    assert res == "123"

    # 4. ARRAY_MAP
    row = {"tags": [{"name": "urgent"}, {"name": "billing"}]}
    res = StructuralTransformEngine.evaluate(
        transform_type=TransformTypeEnum.ARRAY_MAP,
        transform_params={"array_path": "tags", "element_path": "name", "delimiter": ", "},
        source_fields=[],
        row_or_obj=row,
    )
    assert res == "urgent, billing"

    # 5. UNNEST
    row = {"contact": {"email": "test@cinqflow.com", "phone": "555-1234"}}
    res = StructuralTransformEngine.evaluate(
        transform_type=TransformTypeEnum.UNNEST,
        transform_params={"path": "contact"},
        source_fields=[],
        row_or_obj=row,
    )
    assert res == {"email": "test@cinqflow.com", "phone": "555-1234"}
